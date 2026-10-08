// Explicit training helpers. Normal evaluation requires a freshly loaded scene.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using HarmonyLib;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class TrainingCurriculumProfile {
    static string profile="native", family="";
    static int scene=-1, seed, targetId;
    static bool altered;
    static double started;
    static HealthManager target;
    static float center,left,right,anchorY,rate;
    static Vector3 targetOrigin;
    static bool windowPaused;
    static readonly Dictionary<Behaviour,bool> enabled=new Dictionary<Behaviour,bool>();
    static readonly Dictionary<Rigidbody2D,RigidbodyType2D> bodies=new Dictionary<Rigidbody2D,RigidbodyType2D>();
    static readonly Dictionary<Rigidbody2D,float> gravities=new Dictionary<Rigidbody2D,float>();
    static readonly Dictionary<Collider2D,bool> colliders=new Dictionary<Collider2D,bool>();
    static readonly Dictionary<HealthManager,bool> invincible=new Dictionary<HealthManager,bool>();
    static readonly Dictionary<HutongGames.PlayMaker.FsmTransition,string> transitions=new Dictionary<HutongGames.PlayMaker.FsmTransition,string>();
    static readonly Dictionary<HutongGames.PlayMaker.FsmTransition,HutongGames.PlayMaker.FsmState> transitionCache=new Dictionary<HutongGames.PlayMaker.FsmTransition,HutongGames.PlayMaker.FsmState>();
    static readonly Dictionary<DamageHero,int> damageValues=new Dictionary<DamageHero,int>();
    static int schedulerChanges;
    static string schedulerSource="",schedulerDestination="";

    static string Q(string s){return "\""+(s??"").Replace("\\","\\\\").Replace("\"","\\\"")+"\"";}
    static string N(float n){return n.ToString(CultureInfo.InvariantCulture);}
    static List<HealthManager> Actors(){
        var result=new List<HealthManager>();
        foreach(var h in Resources.FindObjectsOfTypeAll<HealthManager>())
            if(h!=null && h.gameObject.scene==UnityEngine.SceneManagement.SceneManager.GetActiveScene() && h.name.ToLowerInvariant().Contains("mantis") && h.name.ToLowerInvariant().Contains("lord") && h.GetComponent<HealthManager>()==h)result.Add(h);
        return result;
    }
    public static void SceneChanged(){
        enabled.Clear();bodies.Clear();gravities.Clear();colliders.Clear();invincible.Clear();transitions.Clear();transitionCache.Clear();damageValues.Clear();
        target=null;profile="native";family="";altered=false;scene=UnityEngine.SceneManagement.SceneManager.GetActiveScene().handle;
        schedulerChanges=0;schedulerSource=schedulerDestination="";
    }
    public static void Restore(){
        foreach(var e in transitions){e.Key.ToState=e.Value;e.Key.ToFsmState=transitionCache[e.Key];}
        foreach(var e in damageValues)if(e.Key!=null)e.Key.damageDealt=e.Value;
        foreach(var e in enabled)if(e.Key!=null)e.Key.enabled=e.Value;
        foreach(var e in colliders)if(e.Key!=null)e.Key.enabled=e.Value;
        foreach(var e in bodies)if(e.Key!=null){e.Key.bodyType=e.Value;e.Key.linearVelocity=Vector2.zero;}
        foreach(var e in gravities)if(e.Key!=null)e.Key.gravityScale=e.Value;
        foreach(var e in invincible)if(e.Key!=null)AccessTools.Field(typeof(HealthManager),"invincible").SetValue(e.Key,e.Value);
        if(target!=null)target.transform.position=targetOrigin;
        enabled.Clear();colliders.Clear();bodies.Clear();gravities.Clear();invincible.Clear();transitions.Clear();transitionCache.Clear();damageValues.Clear();
        target=null;profile="native";family="";
        // altered deliberately remains true until scene reload. Restore alone is
        // insufficient proof that native enemy FSM history is pristine.
    }
    static void Disable(Behaviour b){if(!enabled.ContainsKey(b))enabled[b]=b.enabled;b.enabled=false;}
    static void Bounds(){
        var hero=HeroController.instance;float x=hero.transform.position.x;
        float lo=float.NegativeInfinity,hi=float.PositiveInfinity;
        foreach(var d in UnityEngine.Object.FindObjectsOfType<DamageHero>())if(d.name.ToLowerInvariant().Contains("spike"))
            foreach(var c in d.GetComponentsInChildren<Collider2D>())if(c.enabled && c.gameObject.activeInHierarchy){
                var b=c.bounds;if(b.center.x<x)lo=Math.Max(lo,b.max.x);else hi=Math.Min(hi,b.min.x);
            }
        if(float.IsInfinity(lo)||float.IsInfinity(hi)||hi-lo<5)throw new InvalidOperationException("Unverified safe arena span");
        left=lo+.8f;right=hi-.8f;center=(left+right)/2f;
    }
    public static void Configure(string name,int randomSeed,float speed,string attackFamily){
        if(scene!=UnityEngine.SceneManagement.SceneManager.GetActiveScene().handle)SceneChanged();
        if(!MantisTelemetry.IsEncounter || HeroController.instance==null || profile!="native" || altered)
            throw new InvalidOperationException("Fresh native scene required for curriculum profile");
        if(name=="native")return;
        if(name!="terrain_static" && name!="target_static" && name!="target_motion" && name!="target_window" && name!="boss_single_move")throw new ArgumentException("Unknown curriculum profile");
        var actors=Actors();if(actors.Count!=4)throw new InvalidOperationException("Expected four unique native actors");
        HealthManager first=actors.Find(h=>h.name=="Mantis Lord");
        if(first==null)throw new InvalidOperationException("First-phase identity not found");
        if(randomSeed<0 || float.IsNaN(speed)||float.IsInfinity(speed)||speed<0||speed>40)throw new ArgumentException("Invalid profile seed/speed");
        Bounds();seed=randomSeed;rate=speed;started=Time.fixedTimeAsDouble;family=attackFamily;
        altered=true;
        if(name=="boss_single_move"){
            ConfigureScheduler(first,attackFamily);
        }else{
            foreach(var h in actors){
                foreach(var f in h.GetComponentsInChildren<PlayMakerFSM>(true))Disable(f);
                var rb=h.GetComponent<Rigidbody2D>();if(rb!=null){bodies[rb]=rb.bodyType;gravities[rb]=rb.gravityScale;rb.bodyType=RigidbodyType2D.Kinematic;rb.gravityScale=0;rb.linearVelocity=Vector2.zero;}
            }
            if(name!="terrain_static"){
                if(!first.gameObject.activeInHierarchy)throw new InvalidOperationException("First native target is not active");
                target=first;targetId=first.GetInstanceID();targetOrigin=first.transform.position;
                var field=AccessTools.Field(typeof(HealthManager),"invincible");invincible[first]=(bool)field.GetValue(first);field.SetValue(first,false);
                var c=first.GetComponent<Collider2D>();var hc=HeroController.instance.GetComponent<Collider2D>();
                if(c==null||hc==null)throw new InvalidOperationException("Native target/player collider missing");
                colliders[c]=c.enabled;c.enabled=true;
                float sign=(seed%2==0)?1f:-1f;
                float offset=1.5f+(Math.Abs(seed)%3)*1.2f;
                float px=Mathf.Clamp(hc.bounds.center.x+sign*offset,left+1,right-1);
                first.transform.position+=new Vector3(px-c.bounds.center.x,hc.bounds.center.y-c.bounds.center.y,0);
                anchorY=first.transform.position.y;
                center=first.transform.position.x;
            }
        }
        profile=name;altered=true;Maintain();
    }
    static void ConfigureScheduler(HealthManager first,string attackFamily){
        if(attackFamily!="dash"&&attackFamily!="dstab"&&attackFamily!="throw")throw new ArgumentException("Unknown native attack family");
        PlayMakerFSM fsm=null;foreach(var f in first.GetComponents<PlayMakerFSM>())if(f.FsmName=="Mantis Lord")fsm=f;
        if(fsm==null)throw new InvalidOperationException("Primary native FSM unavailable");
        // Audit topology, not guessed timers. Require one native selector with
        // outgoing paths to all three attack families before editing destinations.
        foreach(var state in fsm.FsmStates){
            var mapped=new Dictionary<string,HutongGames.PlayMaker.FsmTransition>();
            foreach(var tr in state.Transitions){
                string dest=(tr.ToState??"").ToLowerInvariant();
                if(dest.Contains("dash"))mapped["dash"]=tr;
                else if(dest.Contains("dstab"))mapped["dstab"]=tr;
                else if(dest.Contains("throw")||dest.Contains("wall arrive"))mapped["throw"]=tr;
            }
            if(mapped.Count!=3)continue;
            string wanted=mapped[attackFamily].ToState;
            if(state.Name!="Attack Choice")continue;
            var wantedState=Array.Find(fsm.FsmStates,s=>s.Name==wanted);
            if(wantedState==null)throw new InvalidOperationException("Native destination missing");
            foreach(var tr in state.Transitions){string dest=(tr.ToState??"").ToLowerInvariant();if(dest.Contains("dash")||dest.Contains("dstab")||dest.Contains("throw")||tr.EventName=="HIGH THROW"){transitions[tr]=tr.ToState;transitionCache[tr]=tr.ToFsmState;tr.ToState=wanted;tr.ToFsmState=wantedState;}}
            schedulerSource=state.Name;schedulerDestination=wanted;schedulerChanges=transitions.Count;return;
        }
        throw new InvalidOperationException("No audited native three-family selector; single-move profile blocked");
    }
    public static void Maintain(){
        if(scene!=UnityEngine.SceneManagement.SceneManager.GetActiveScene().handle){SceneChanged();return;}
        if(profile=="native"||profile=="boss_single_move")return;
        foreach(var d in UnityEngine.Object.FindObjectsOfType<DamageHero>())if(!d.name.ToLowerInvariant().Contains("spike")){if(!damageValues.ContainsKey(d))damageValues[d]=d.damageDealt;d.damageDealt=0;Disable(d);}
    }
    public static void Tick(){
        Maintain();if((profile!="target_motion" && profile!="target_window")||target==null)return;
        float elapsed=(float)(Time.fixedTimeAsDouble-started);
        float span=Math.Min(3f,Math.Min(center-left,right-center));
        if(span<.2f)throw new InvalidOperationException("Moving-target span too small");
        windowPaused=false;
        float travel=Mathf.PingPong(elapsed*rate+span,span*2)-span;
        if(profile=="target_window") {
            if(rate<=0){travel=0;windowPaused=true;}
            else {
                float move=2*span/rate, pause=.45f;
                float phase=(elapsed+span/rate)%(2*move+2*pause);
                if(phase<move)travel=-span+rate*phase;
                else if(phase<move+pause){travel=span;windowPaused=true;}
                else if(phase<2*move+pause)travel=span-rate*(phase-move-pause);
                else {travel=-span;windowPaused=true;}
            }
        }
        target.transform.position=new Vector3(center+travel,anchorY,target.transform.position.z);
        var rb=target.GetComponent<Rigidbody2D>();if(rb!=null)rb.linearVelocity=Vector2.zero;
    }
    static string TargetGeometry(){
        HealthManager actor=target;
        if(actor==null && HeroController.instance!=null){
            float distance=float.PositiveInfinity;
            foreach(var a in Actors())if(a.gameObject.activeInHierarchy && a.hp>0){
                float d=(a.transform.position-HeroController.instance.transform.position).sqrMagnitude;
                if(d<distance){actor=a;distance=d;}
            }
        }
        var c=actor!=null?actor.GetComponent<Collider2D>():null;
        var box=c!=null?c.bounds:new Bounds(Vector3.zero,Vector3.zero);
        return ",\"profile_version\":6,\"target_valid\":"+(c!=null && c.enabled && c.gameObject.activeInHierarchy?"true":"false")+
            ",\"target_cx\":"+N(box.center.x)+",\"target_cy\":"+N(box.center.y)+",\"target_ex\":"+N(box.extents.x)+",\"target_ey\":"+N(box.extents.y)+
            ",\"window_paused\":"+(profile=="target_window" && windowPaused?"true":"false");
    }
    public static string State(){
        if(scene!=UnityEngine.SceneManagement.SceneManager.GetActiveScene().handle)SceneChanged();
        return "{\"profile\":"+Q(profile)+",\"altered_mechanisms\":"+(altered?"true":"false")+",\"formal_integrity\":"+(!altered&&profile=="native"?"true":"false")+
            ",\"seed\":"+seed+",\"target_id\":"+targetId+",\"speed\":"+N(rate)+",\"safe_left\":"+N(left)+",\"safe_right\":"+N(right)+
            ",\"attack_family\":"+Q(family)+",\"scheduler_source\":"+Q(schedulerSource)+",\"scheduler_destination\":"+Q(schedulerDestination)+",\"scheduler_changes\":"+schedulerChanges+TargetGeometry()+"}";
    }
    public static string Graph(){
        var b=new StringBuilder("{\"actors\":[");bool comma=false;
        foreach(var h in Actors())foreach(var f in h.GetComponentsInChildren<PlayMakerFSM>(true))if(f.FsmName=="Mantis Lord"){
            if(comma)b.Append(',');comma=true;b.Append("{\"actor\":"+Q(h.name)+",\"states\":[");bool sc=false;
            foreach(var s in f.FsmStates){if(sc)b.Append(',');sc=true;b.Append("{\"name\":"+Q(s.Name)+",\"transitions\":[");bool tc=false;
                foreach(var t in s.Transitions){if(tc)b.Append(',');tc=true;b.Append("{\"event\":"+Q(t.EventName)+",\"to\":"+Q(t.ToState)+"}");}b.Append("]}");}
            b.Append("]}");
        }return b.Append("]}").ToString();
    }
}
