"""Hornet protocol, observation, event checks and durable sample accounting."""
import json
import os
import socket
import time
import atexit
from pathlib import Path
import numpy as np

SCHEMA='hornet-lstm-v1'
LIMIT=200000
STAGE_LIMITS=(20000,80000,100000)
HEADS=(3,2,4,2)
HAZARDS=32

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',encoding='utf8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)

_socket=None
_reader=None
def disconnect():
    global _socket,_reader
    if _reader is not None:_reader.close()
    if _socket is not None:_socket.close()
    _socket=_reader=None
atexit.register(disconnect)

def request(command):
    global _socket,_reader
    try:
        if _socket is None:
            _socket=socket.create_connection(('127.0.0.1',9851),timeout=10)
            _socket.settimeout(35);_reader=_socket.makefile('rb')
        _socket.sendall((command+'\n').encode())
        raw=_reader.readline()
    except Exception:
        disconnect()
        raise # Never replay an action with an unknown execution outcome.
    data=json.loads(raw)
    if 'error' in data:raise RuntimeError((command,data))
    return data

def reset():
    request('hornet reset')
    end=time.monotonic()+30
    while time.monotonic()<end:
        time.sleep(.1);s=request('state')
        h=s.get('hornet',{})
        if s['scene']=='GG_Hornet_1' and h.get('valid') and s['body_type']==0 and s['grounded'] and not s['invulnerable']:
            request('mode combat');s=request('sync on')
            if s['hp']!=9 or s['soul']!=0 or s['hornet']['hurt'] or s['hornet']['damage']:raise RuntimeError('Opening already changed before synchronized sampling')
            if s['hasShadowDash'] or s['hasDoubleJump'] or s['hornet']['nail_damage']!=9:raise RuntimeError('Player configuration mismatch')
            return s
    raise RuntimeError('Hornet entry did not become physically ready')

def action_mask(s):
    return np.array([1,1,1,1,bool(s['can_jump'] or s['input_mask']&4),1,bool(s['can_attack']),bool(s['can_attack']),bool(s['can_attack']),1,bool(s['can_dash'])],dtype=np.float32)

def buttons(action,s):
    move,jump,nail,dash=map(int,action)
    if not(0<=move<3 and 0<=jump<2 and 0<=nail<4 and 0<=dash<2):raise ValueError('Invalid action')
    masks=action_mask(s);offset=0
    for x,n in zip((move,jump,nail,dash),HEADS):
        if not masks[offset+x]:raise ValueError('Unavailable action')
        offset+=n
    mask=(1 if move==1 else 2 if move==2 else 0)|(4 if jump else 0)|(8 if nail else 0)|(16 if dash else 0)|(128 if nail==2 else 32 if nail==3 else 0)
    return mask,mask&(8|16) # jump is held, never artificially retriggered

def validate(old,new):
    if new['scene']!='GG_Hornet_1':raise RuntimeError('Unexpected scene transition')
    a,b=old['hornet'],new['hornet']
    if a['epoch']!=b['epoch'] or a['actor']!=b['actor']:raise RuntimeError('Actor identity changed')
    dt=new['time']-old['time']
    if new['physics_ticks']-old['physics_ticks']!=2 or abs(dt-.04)>.001:raise RuntimeError('Physics step contract violated')
    if new['hazard_count']>HAZARDS:raise RuntimeError('Hazard observation overflow')
    if new['hero_healed'] or new['soul']<0:raise RuntimeError('Unexpected resource event')
    for k in ['damage','hurt','hits','attacks']:
        if b[k]<a[k]:raise RuntimeError('Counter rolled back: '+k)
    for counter,kind in [('damage','damage'),('hurt','hurt')]:
        if b[counter]-a[counter]!=sum(e['amount'] for e in b['events'] if e['kind']==kind):raise RuntimeError('Event reconciliation failed: '+counter)
    if old['hp']-new['hp']!=b['hurt']-a['hurt']:raise RuntimeError('HP and damage event mismatch')
    if b['valid'] and a['hp']-b['hp']!=b['damage']-a['damage']:raise RuntimeError('Boss HP and damage mismatch')
    if b['damage']>b['max_hp']:raise RuntimeError('Boss damage exceeds initial HP')
    return dt

def won(s):
    h=s['hornet']
    return bool(h['native_death'] and h['complete'] and h['bosses_dead'] and s['hp']>0)

def observation(s,phases,elapsed,cap):
    h=s['hornet'];x,y=s['x'],s['y']
    features=[s['hp']/9,h['hp']/max(h['max_hp'],1),s['vx']/30,s['vy']/30,(h['x']-x)/30,(h['y']-y)/20,h['vx']/30,h['vy']/30,min(h['phase_age']/5,1),elapsed/120,cap/9]
    flags=['grounded','facing_right','invulnerable','dashing','hero_attacking','hero_recoiling','can_jump','can_attack','can_dash']
    features += [float(s[k]) for k in flags]
    features += [float(bool(s['input_mask']&(1<<i))) for i in range(9)]
    features += [min(float(v)/20,1) for v in s['terrain_distances']+s['floor_distances']]
    features += [float(v) for v in s['terrain_hits']]
    for i in range(HAZARDS):
        if i<len(s['hazards']):
            z=s['hazards'][i];features += [1,(z['cx']-x)/30,(z['cy']-y)/20,z['ex']/10,z['ey']/10,z['vx']/30,z['vy']/30,z['velocity_valid']]
        else:features += [0]*8
    features += [float(h['phase']==p) for p in phases]+[float(h['phase'] not in phases)]
    result=np.r_[np.clip(features,-5,5),action_mask(s)].astype(np.float32)
    if not np.isfinite(result).all():raise RuntimeError('Nonfinite observation')
    return result

def reward(old,new,coeff,ended=False,timeout=False):
    a,b=old['hornet'],new['hornet']
    parts={'damage':(b['damage']-a['damage'])/9,'hurt':-coeff['hurt']*(b['hurt']-a['hurt'])}
    if won(new):parts['win']=coeff['win'];parts['flawless']=coeff['flawless'] if b['hurt']==0 else 0
    elif ended and new['hp']<=0:parts['death']=-coeff['death']
    elif ended and timeout:parts['timeout']=-coeff['timeout']
    return parts

class Ledger:
    def __init__(self,path):
        self.path=Path(path)
        self.data=json.loads(self.path.read_text()) if self.path.exists() else dict(actual=0,effective=0,evaluation=0,stage=0,stage_actual=[0,0,0],pending=None)
        if self.data['pending'] is not None:raise RuntimeError('Uncertain executed action: reconcile before resuming')
    def reserve(self,training):
        d=self.data
        if d['pending'] is not None:raise RuntimeError('Pending action')
        if training and (d['actual']>=LIMIT or d['stage_actual'][d['stage']]>=STAGE_LIMITS[d['stage']]):raise RuntimeError('Hard budget exhausted')
        d['pending']='training' if training else 'evaluation';write_json(self.path,d)
    def settle(self):
        d=self.data
        if d['pending']=='training':d['actual']+=1;d['stage_actual'][d['stage']]+=1
        elif d['pending']=='evaluation':d['evaluation']+=1
        else:raise RuntimeError('No reserved action')
        d['pending']=None;write_json(self.path,d)
