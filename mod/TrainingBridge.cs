using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Collections;
using System.Collections.Generic;
using System.Threading;
using System.Reflection;
using BepInEx;
using HarmonyLib;
using UnityEngine;
using UnityEngine.SceneManagement;
using InControl;

[DefaultExecutionOrder(-10000)]
[BepInPlugin("local.pantheon.training", "Pantheon Training Bridge", "0.1.0")]
public class TrainingBridge : BaseUnityPlugin {
    TcpListener listener;
    Queue<Request> requests = new Queue<Request>();
    bool busy;
    bool defenseOnly;
    bool syncMode, advancing;
    int physicsTicks, inputMask;
    string lastBossPhase=""; float phaseSince; int phaseEvent;
    Dictionary<int,Vector2> hazardPositions=new Dictionary<int,Vector2>();
    Dictionary<int,float> hazardTimes=new Dictionary<int,float>();
    bool queuedInput;
    int queuedMask;
    float lastContact;
    Dictionary<OneAxisInputControl, int> inputs = new Dictionary<OneAxisInputControl, int>();
    static TrainingBridge self;
    bool[] held = new bool[9], previous = new bool[9];
    HealthManager boss;
    int maxBossHp;
    int effectiveHits, damageDealt;
    bool sawBoss, won, resetting, displayChecked;
    float loadedAt;
    class Request { public string text, result; public ManualResetEvent done = new ManualResetEvent(false); }
    void Awake() {
        self = this;
        Application.runInBackground=true;
        Application.targetFrameRate=120;
        UnityEngine.SceneManagement.SceneManager.sceneLoaded += delegate(UnityEngine.SceneManagement.Scene s, LoadSceneMode mode) {
            if(s.name=="GG_Gruz_Mother") { boss=null; maxBossHp=0; effectiveHits=0; damageDealt=0; sawBoss=false; won=false; resetting=false; displayChecked=false; loadedAt=Time.time; }
        };
        var harmony = new Harmony("local.pantheon.training");
        harmony.Patch(AccessTools.Method(typeof(HealthManager), "Die"), new HarmonyMethod(typeof(TrainingBridge), "BossDied"));
        harmony.Patch(AccessTools.Method(typeof(HealthManager), "TakeDamage"), new HarmonyMethod(typeof(TrainingBridge), "BeforeDamage"), new HarmonyMethod(typeof(TrainingBridge), "AfterDamage"));
        foreach (string name in new string[]{"IsPressed", "State", "WasPressed", "WasReleased", "Value", "RawValue"}) {
            var getter = AccessTools.PropertyGetter(typeof(OneAxisInputControl), name);
            if (getter != null) harmony.Patch(getter, new HarmonyMethod(typeof(TrainingBridge), name == "Value" || name == "RawValue" ? "FloatInput" : "BoolInput"));
        }
        // Training must never write progress to personal or cloned save slots.
        foreach (var method in typeof(GameManager).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
            if (method.Name == "SaveGame") harmony.Patch(method, new HarmonyMethod(typeof(TrainingBridge), "NoSave"));
        listener = new TcpListener(IPAddress.Loopback, 9851); listener.Start();
        new Thread(Serve){IsBackground=true}.Start();
        Logger.LogInfo("Training bridge listening on 127.0.0.1:9851; saving disabled while installed");
    }
    static bool NoSave() { return false; }
    static void BeforeDamage(HealthManager __instance, out int __state) { __state=__instance.hp; }
    static void AfterDamage(HealthManager __instance, int __state) {
        if(self!=null && !self.resetting && self.boss==__instance && __instance.hp<__state) {
            self.effectiveHits++;
            self.damageDealt+=Math.Min(__state, __state-__instance.hp);
        }
    }
    static void BossDied(HealthManager __instance) {
        if(self!=null && !self.resetting && self.boss==__instance) {
            self.won=true;
            self.Logger.LogInfo("Confirmed Gruz Mother death event");
        }
    }
    static bool FloatInput(OneAxisInputControl __instance, ref float __result) {
        int i; if (self == null || !self.inputs.TryGetValue(__instance,out i)) return true;
        __result = self.held[i] && __instance.EnabledInHierarchy ? 1f : 0f; return false;
    }
    static bool BoolInput(OneAxisInputControl __instance, MethodBase __originalMethod, ref bool __result) {
        int i; if (self == null || !self.inputs.TryGetValue(__instance,out i)) return true;
        string n=__originalMethod.Name;
        __result=__instance.EnabledInHierarchy && (n=="get_WasPressed" ? self.held[i]&&!self.previous[i] : n=="get_WasReleased" ? !self.held[i]&&self.previous[i] : self.held[i]); return false;
    }
    void Serve() {
        try { while(true) {
            try { using(var client=listener.AcceptTcpClient()) using(var stream=client.GetStream())
            using(var reader=new StreamReader(stream)) using(var writer=new StreamWriter(stream){AutoFlush=true}) {
                string line; while((line=reader.ReadLine())!=null) {
                    var r=new Request{text=line}; lock(requests) requests.Enqueue(r);
                    if(!r.done.WaitOne(30000)) { writer.WriteLine("{\"error\":\"main thread timeout\"}"); break; }
                    writer.WriteLine(r.result);
                }
            }} catch(Exception e) { Array.Clear(held,0,held.Length); Logger.LogWarning("Client disconnected: "+e.Message); }
        }} catch(Exception e) { Logger.LogWarning(e.Message); }
    }
    void FixedUpdate() { physicsTicks++; }
    void Update() {
        if(syncMode && !advancing) Time.timeScale=0f;
        if(queuedInput) {
            for(int i=0;i<held.Length;i++) held[i]=(queuedMask&(1<<i))!=0;
            inputMask=queuedMask;queuedInput=false;
        }
        if(inputs.Count==0 && InputHandler.Instance!=null && InputHandler.Instance.inputActions!=null) {
            var a=InputHandler.Instance.inputActions;
            OneAxisInputControl[] controls={a.left,a.right,a.jump,a.attack,a.dash,a.down,a.quickCast,a.up,a.focus};
            for(int i=0;i<controls.Length;i++) inputs[controls[i]]=i;
            inputs[a.cast]=8; // The game's ListenForCast FSM handles hold-to-focus via cast.
            Logger.LogInfo("Input bound");
        }
        if(Time.realtimeSinceStartup-lastContact>35f) { Array.Clear(held,0,held.Length); if(syncMode) { advancing=false; Time.timeScale=0f; } }
        if(!busy) { Request r=null; lock(requests) if(requests.Count>0) r=requests.Dequeue();
            if(r!=null) { busy=true; lastContact=Time.realtimeSinceStartup; StartCoroutine(Execute(r)); }
        }
    }
    void LateUpdate() { Array.Copy(held,previous,held.Length); }
    IEnumerator Execute(Request r) {
        if(r.text.StartsWith("tick ")) {
            int mask=0,pulse=0;
            try {
                string[] a=r.text.Split(' ');mask=int.Parse(a[1]);pulse=int.Parse(a[2]);
                if(!syncMode || mask<0 || mask>511 || pulse<0 || pulse>511 || (defenseOnly && (mask & ~23)!=0))throw new ArgumentException();
            } catch(Exception e) { r.result="{\"error\":\""+e.GetType().Name+"\"}"; }
            if(r.result==null) {
                inputMask=mask & ~pulse;
                for(int i=0;i<held.Length;i++)held[i]=(inputMask&(1<<i))!=0;
                advancing=true;Time.timeScale=1f;
                int start=physicsTicks;
                if(pulse!=0) {
                    while(physicsTicks<start+1)yield return new WaitForFixedUpdate();
                    queuedMask=mask;queuedInput=true;
                    while(queuedInput)yield return null;
                }
                else inputMask=mask;
                while(physicsTicks<start+4)yield return new WaitForFixedUpdate();
                advancing=false;Time.timeScale=0f;
                try { r.result=State(); }catch(Exception e){r.result="{\"error\":\""+e.GetType().Name+"\"}";Logger.LogError(e);}
            }
            r.done.Set();busy=false;yield break;
        }
        bool stepping=r.text.StartsWith("step ") || r.text.StartsWith("pulse ");
        int pulseMask=0, pulseBits=0;
        if(r.text.StartsWith("pulse ")) {
            try {
                string[] parts=r.text.Split(' ');
                pulseMask=int.Parse(parts[1]); pulseBits=int.Parse(parts[2]);
                if(pulseMask<0 || pulseMask>511 || pulseBits<0 || pulseBits>511) throw new ArgumentException();
                if(defenseOnly && (pulseMask & ~23)!=0) throw new ArgumentException();
                for(int i=0;i<held.Length;i++) held[i]=((pulseMask & ~pulseBits)&(1<<i))!=0;
            } catch(Exception) { r.result="{\"error\":\"invalid pulse\"}"; }
            if(r.result==null && pulseBits!=0) {
                // Release was applied in early Update. Queue the press for a
                // later early Update, never from the post-Update coroutine.
                yield return null;
                queuedMask=pulseMask;queuedInput=true;
                while(queuedInput) yield return null;
            }

        }
        try {
            if(r.text=="sync on") { syncMode=true;advancing=false;Time.timeScale=0f; }
            else if(r.text=="sync off") { syncMode=false;advancing=false;Time.timeScale=1f; }
            else if(r.text=="mode dodge") {
                defenseOnly=true;
                Logger.LogInfo("Dodge mode infiniteAirJump before normalization: "+PlayerData.instance.infiniteAirJump);
                PlayerData.instance.infiniteAirJump=false;
            }
            else if(r.text=="mode combat") defenseOnly=false;
            else if(r.text=="probe resources") {
                if(defenseOnly)throw new InvalidOperationException("Diagnostics forbidden in defense training");
                PlayerData.instance.health=Math.Max(1,PlayerData.instance.maxHealth-1);PlayerData.instance.MPCharge=99;
            }
            else if(r.text.StartsWith("speed ")) {
                float speed=float.Parse(r.text.Substring(6),System.Globalization.CultureInfo.InvariantCulture);
                if(speed!=1f && speed!=2f) throw new ArgumentException();
                Time.timeScale=speed;
            }
            else if(r.text=="load") GameManager.instance.LoadGameFromUI(4);
            else if(r.text=="reset") {
                Array.Clear(held,0,held.Length);inputMask=0;advancing=true;Time.timeScale=1f;hazardPositions.Clear();hazardTimes.Clear();lastBossPhase="";phaseEvent=0; resetting=true; boss=null; maxBossHp=0; sawBoss=false; won=false;
                BossSequenceController.Reset();
                PlayerData.instance.currentBossSequence=null;
                PlayerData.instance.health=PlayerData.instance.maxHealth;
                if(defenseOnly)PlayerData.instance.MPCharge=0;
                PlayerData.instance.bossStatueTargetLevel=0;
                GameManager.instance.BeginSceneTransition(new GameManager.SceneLoadInfo { SceneName="GG_Gruz_Mother", EntryGateName="door_dreamEnter", EntryDelay=0f, Visualization=GameManager.SceneLoadVisualizations.GodsAndGlory });
            } else if(r.text.StartsWith("step ")) {
                int mask=int.Parse(r.text.Substring(5)); if(defenseOnly && (mask & ~23)!=0) throw new ArgumentException(); for(int i=0;i<held.Length;i++) held[i]=(mask&(1<<i))!=0;
            } else if(r.text=="release") { Array.Clear(held,0,held.Length); Time.timeScale=1f; defenseOnly=false;syncMode=false;advancing=false; }
        } catch(Exception e) { r.result="{\"error\":\""+e.GetType().Name+"\"}"; }
        if(stepping && r.result==null) for(int i=0;i<3;i++) yield return new WaitForFixedUpdate();
        if(r.result==null) { try { r.result=State(); } catch(Exception e) { r.result="{\"error\":\""+e.GetType().Name+"\"}"; Logger.LogError(e); } }
        r.done.Set(); busy=false;
    }
    static string Numeric(object target, string name) {
        if(target==null) return "0";
        var f=AccessTools.Field(target.GetType(),name);
        if(f==null) throw new MissingFieldException(target.GetType().Name,name);
        object value=f.GetValue(target);
        return value is bool ? ((bool)value?"1":"0") : Convert.ToString(value,System.Globalization.CultureInfo.InvariantCulture);
    }
    static string BoundsJson(string prefix, GameObject obj) {
        var c=obj!=null?obj.GetComponent<Collider2D>():null;
        Bounds b=c!=null?c.bounds:new Bounds(obj!=null?obj.transform.position:Vector3.zero,Vector3.zero);
        return string.Format(System.Globalization.CultureInfo.InvariantCulture,
            ",\"{0}cx\":{1},\"{0}cy\":{2},\"{0}ex\":{3},\"{0}ey\":{4}",prefix,b.center.x,b.center.y,b.extents.x,b.extents.y);
    }
    string GeometryJson(HeroController hero) {
        var ci=System.Globalization.CultureInfo.InvariantCulture;
        var output=new System.Text.StringBuilder();
        int layer=LayerMask.NameToLayer("Terrain");
        output.Append(",\"terrain_valid\":"+(layer>=0?"true":"false")+",\"terrain_distances\":[");
        Vector2 center=hero!=null?(Vector2)hero.GetComponent<Collider2D>().bounds.center:Vector2.zero;
        Vector2 ext=hero!=null?(Vector2)hero.GetComponent<Collider2D>().bounds.extents:Vector2.zero;
        Vector2[] dirs={Vector2.left,Vector2.right,Vector2.down,Vector2.up,new Vector2(-1,-1).normalized,new Vector2(1,-1).normalized,new Vector2(-1,1).normalized,new Vector2(1,1).normalized};
        bool[] hits=new bool[8];
        for(int i=0;i<8;i++) {
            RaycastHit2D hit=layer>=0?Physics2D.Raycast(center,dirs[i],20f,1<<layer):new RaycastHit2D();
            hits[i]=hit.collider!=null;
            float distance=hits[i]?Math.Max(0,hit.distance-Math.Abs(dirs[i].x)*ext.x-Math.Abs(dirs[i].y)*ext.y):20f;
            if(i>0)output.Append(",");output.Append(distance.ToString(ci));
        }
        output.Append("],\"terrain_hits\":[");
        for(int i=0;i<8;i++){if(i>0)output.Append(",");output.Append(hits[i]?"1":"0");}
        output.Append("],\"hazards\":[");
        var colliders=new System.Collections.Generic.List<Collider2D>();
        var sources=new System.Collections.Generic.Dictionary<Collider2D,DamageHero>();
        foreach(var damage in UnityEngine.Object.FindObjectsOfType<DamageHero>()) {
            if(!damage.enabled || !damage.gameObject.activeInHierarchy || damage.damageDealt<=0)continue;
            foreach(var c in damage.GetComponentsInChildren<Collider2D>()) {
                if(c.enabled && c.gameObject.activeInHierarchy && c.GetComponentInParent<DamageHero>()==damage && !sources.ContainsKey(c)) {colliders.Add(c);sources[c]=damage;}
            }
        }
        colliders.Sort((a,b)=>HazardPriority(a,center).CompareTo(HazardPriority(b,center)));
        for(int i=0;i<Math.Min(6,colliders.Count);i++) {
            var c=colliders[i];var d=sources[c];var b=c.bounds;var rb=c.attachedRigidbody;
            Vector2 v=rb!=null?rb.linearVelocity:Vector2.zero;
            int id=c.GetInstanceID();Vector2 before;float beforeTime;
            bool velocityValid=rb!=null;
            if(rb==null && hazardPositions.TryGetValue(id,out before) && hazardTimes.TryGetValue(id,out beforeTime) && Time.time>beforeTime) {v=((Vector2)b.center-before)/(Time.time-beforeTime);velocityValid=true;}
            if(!hazardTimes.ContainsKey(id) || Time.time>hazardTimes[id]) {hazardPositions[id]=(Vector2)b.center;hazardTimes[id]=Time.time;}
            int kind=boss!=null && (c.transform==boss.transform || c.transform.IsChildOf(boss.transform))?1:2;
            if(i>0)output.Append(",");
            output.Append(string.Format(ci,"{{\"cx\":{0},\"cy\":{1},\"ex\":{2},\"ey\":{3},\"vx\":{4},\"vy\":{5},\"damage\":{6},\"shadow_hazard\":{7}}}",b.center.x,b.center.y,b.extents.x,b.extents.y,v.x,v.y,d.damageDealt,d.shadowDashHazard?1:0));
            output.Length--;output.Append(",\"id\":"+id+",\"kind\":"+kind+",\"velocity_valid\":"+(velocityValid?1:0)+"}");
        }
        output.Append("],\"hazard_count\":"+colliders.Count);
        output.Append(",\"floor_distances\":[");
        for(int i=-1;i<=1;i++) {
            var hit=layer>=0?Physics2D.Raycast(center+new Vector2(i*ext.x*.9f,0),Vector2.down,20f,1<<layer):new RaycastHit2D();
            if(i>-1)output.Append(",");output.Append((hit.collider!=null?Math.Max(0,hit.distance-ext.y):20f).ToString(ci));
        }
        output.Append("]");return output.ToString();
    }
    static float HazardPriority(Collider2D c,Vector2 center) {
        Vector2 delta=(Vector2)c.bounds.center-center;
        var rb=c.attachedRigidbody;Vector2 v=rb!=null?rb.linearVelocity:Vector2.zero;
        float t= v.sqrMagnitude>.01f ? -Vector2.Dot(delta,v)/v.sqrMagnitude : 10f;
        float miss=(delta+v*Math.Max(0,Math.Min(t,1f))).magnitude;
        return miss+Math.Max(0,t)*.1f;
    }
    string State() {
        var hero=HeroController.instance; var pd=PlayerData.instance;
        string scene=UnityEngine.SceneManagement.SceneManager.GetActiveScene().name;
        if(!resetting && scene=="GG_Gruz_Mother" && boss==null && !sawBoss) {
            foreach(var h in UnityEngine.Object.FindObjectsOfType<HealthManager>())
                if(h.gameObject.name.IndexOf("Gruz",StringComparison.OrdinalIgnoreCase)>=0 || h.gameObject.name.IndexOf("Giant Fly",StringComparison.OrdinalIgnoreCase)>=0) {
                    boss=h; maxBossHp=h.hp; sawBoss=true; Logger.LogInfo("Boss found: "+h.name+" hp="+h.hp); break;
                }
        }
        if(sawBoss && boss!=null && boss.hp<=0) won=true;
        Vector3 p=hero!=null?hero.transform.position:Vector3.zero, b=boss!=null?boss.transform.position:Vector3.zero;
        var rb=hero!=null?hero.GetComponent<Rigidbody2D>():null; var br=boss!=null?boss.GetComponent<Rigidbody2D>():null;
        Vector2 v=rb!=null?rb.linearVelocity:Vector2.zero, bv=br!=null?br.linearVelocity:Vector2.zero;
        bool ready=!resetting && Time.time-loadedAt>2f && scene=="GG_Gruz_Mother" && hero!=null && boss!=null && sawBoss && !won && pd.health>0 && !hero.cState.transitioning;
        // Direct arena entry can leave the normal transition fade covering the
        // screen. Use the game's own fail-safe event, only after entry is ready.
        if(ready && !displayChecked && GameCameras.instance!=null) {
            var fade=AccessTools.Field(typeof(GameCameras),"cameraFadeFSM").GetValue(GameCameras.instance);
            if(fade!=null) {
                string fadeState=(string)AccessTools.Property(fade.GetType(),"ActiveStateName").GetValue(fade,null);
                Logger.LogInfo("Arena display fade state: "+fadeState);
                if(fadeState!="Normal") {
                    var fsm=AccessTools.Property(fade.GetType(),"Fsm").GetValue(fade,null);
                    AccessTools.Method(fsm.GetType(),"Event",new Type[]{typeof(string)}).Invoke(fsm,new object[]{"FADE SCENE IN"});
                    Logger.LogInfo("Requested normal scene fade-in");
                }
                displayChecked=true;
            }
        }
        string payload=string.Format(System.Globalization.CultureInfo.InvariantCulture,
            "{{\"scene\":\"{0}\",\"ready\":{1},\"won\":{2},\"hp\":{3},\"boss_hp\":{4},\"boss_max_hp\":{5},\"soul\":{6},\"x\":{7},\"y\":{8},\"vx\":{9},\"vy\":{10},\"bx\":{11},\"by\":{12},\"bvx\":{13},\"bvy\":{14},\"grounded\":{15},\"frame\":{16},\"time\":{17}}}",
            scene,ready.ToString().ToLower(),won.ToString().ToLower(),pd!=null?pd.health:0,boss!=null?boss.hp:0,maxBossHp,pd!=null?pd.MPCharge:0,p.x,p.y,v.x,v.y,b.x,b.y,bv.x,bv.y,hero!=null&&hero.cState.onGround?1:0,Time.frameCount,syncMode?Time.fixedTime:Time.time);
        Camera camera=GameCameras.instance!=null?(Camera)AccessTools.Field(typeof(GameCameras),"mainCamera").GetValue(GameCameras.instance):Camera.main;
        string view="";
        if(camera!=null && hero!=null) {
            var plane=new Plane(Vector3.forward,hero.transform.position);
            Ray lower=camera.ViewportPointToRay(new Vector3(0,0,0)),upper=camera.ViewportPointToRay(new Vector3(1,1,0));
            float d1,d2;
            if(plane.Raycast(lower,out d1) && plane.Raycast(upper,out d2)) {
                Vector3 v1=lower.GetPoint(d1),v2=upper.GetPoint(d2);
                view=string.Format(System.Globalization.CultureInfo.InvariantCulture,
                    ",\"view_left\":{0},\"view_right\":{1},\"view_bottom\":{2},\"view_top\":{3}",
                    Math.Min(v1.x,v2.x),Math.Max(v1.x,v2.x),Math.Min(v1.y,v2.y),Math.Max(v1.y,v2.y));
            }
        }
        string skills=GeometryJson(hero)+view+BoundsJson("hero_",hero!=null?hero.gameObject:null)+BoundsJson("boss_",boss!=null?boss.gameObject:null);
        string phase="";string[] phaseNames=new string[0];
        if(boss!=null) foreach(var f in boss.GetComponents<PlayMakerFSM>())
            if(f.FsmName.IndexOf("Control",StringComparison.OrdinalIgnoreCase)>=0) { phase=f.ActiveStateName;phaseNames=Array.ConvertAll(f.FsmStates,state=>state.Name);Array.Sort(phaseNames,StringComparer.Ordinal); break; }
        skills+=",\"boss_phase\":\""+phase.Replace("\\","\\\\").Replace("\"","\\\"")+"\"";
        if(phase!=lastBossPhase) {lastBossPhase=phase;phaseSince=Time.time;phaseEvent++;}
        skills+=",\"boss_phase_names\":["+string.Join(",",Array.ConvertAll(phaseNames,n=>"\""+n.Replace("\\","\\\\").Replace("\"","\\\"")+"\""))+"],\"boss_phase_age\":"+(Time.time-phaseSince).ToString(System.Globalization.CultureInfo.InvariantCulture)+",\"boss_phase_event\":"+phaseEvent+",\"physics_ticks\":"+physicsTicks+",\"input_mask\":"+inputMask+",\"sync_paused\":"+(syncMode&&!advancing?"true":"false");
        skills+=",\"facing_right\":"+Numeric(hero!=null?hero.cState:null,"facingRight");
        foreach(string n in new string[]{"infiniteAirJump","equippedCharm_35","equippedCharm_12","equippedCharm_10","equippedCharm_22","equippedCharm_40"})
            skills+=",\""+n+"\":"+Numeric(pd,n);
        foreach(string name in new string[]{"shadowDashTimer","dashCooldownTimer","attack_cooldown","nailChargeTimer","nailChargeTime","doubleJumped","jump_steps","doubleJump_steps","ledgeBufferSteps","touchingWallL","touchingWallR"})
            skills+=",\""+name+"\":"+Numeric(hero,name);
        foreach(string name in new string[]{"invulnerable","shadowDashing","dashing","spellQuake","wallSliding","jumping","doubleJumping"})
            skills+=",\""+name+"\":"+Numeric(hero!=null?hero.cState:null,name);
        foreach(string name in new string[]{"hasShadowDash","fireballLevel","quakeLevel","screamLevel","hasDashSlash","hasUpwardSlash","hasCyclone","equippedCharm_33"})
            skills+=",\""+name+"\":"+Numeric(pd,name);
        return payload.Substring(0,payload.Length-1)+skills+",\"effective_hits\":"+effectiveHits+",\"damage_dealt\":"+damageDealt+"}";
    }
    void OnDestroy() { Array.Clear(held,0,held.Length); if(listener!=null)listener.Stop(); }
}
