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

[BepInPlugin("local.pantheon.training", "Pantheon Training Bridge", "0.1.0")]
public class TrainingBridge : BaseUnityPlugin {
    TcpListener listener;
    Queue<Request> requests = new Queue<Request>();
    bool busy;
    float lastContact;
    Dictionary<OneAxisInputControl, int> inputs = new Dictionary<OneAxisInputControl, int>();
    static TrainingBridge self;
    bool[] held = new bool[7], previous = new bool[7];
    HealthManager boss;
    int maxBossHp;
    bool sawBoss, won, resetting;
    float loadedAt;
    class Request { public string text, result; public ManualResetEvent done = new ManualResetEvent(false); }
    void Awake() {
        self = this;
        Application.runInBackground=true;
        Application.targetFrameRate=120;
        UnityEngine.SceneManagement.SceneManager.sceneLoaded += delegate(UnityEngine.SceneManagement.Scene s, LoadSceneMode mode) {
            if(s.name=="GG_Gruz_Mother") { boss=null; maxBossHp=0; sawBoss=false; won=false; resetting=false; loadedAt=Time.time; }
        };
        var harmony = new Harmony("local.pantheon.training");
        harmony.Patch(AccessTools.Method(typeof(HealthManager), "Die"), new HarmonyMethod(typeof(TrainingBridge), "BossDied"));
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
            using(var client=listener.AcceptTcpClient()) using(var stream=client.GetStream())
            using(var reader=new StreamReader(stream)) using(var writer=new StreamWriter(stream){AutoFlush=true}) {
                string line; while((line=reader.ReadLine())!=null) {
                    var r=new Request{text=line}; lock(requests) requests.Enqueue(r);
                    if(!r.done.WaitOne(30000)) { writer.WriteLine("{\"error\":\"main thread timeout\"}"); break; }
                    writer.WriteLine(r.result);
                }
            }
        }} catch(Exception e) { Logger.LogWarning(e.Message); }
    }
    void Update() {
        if(inputs.Count==0 && InputHandler.Instance!=null && InputHandler.Instance.inputActions!=null) {
            var a=InputHandler.Instance.inputActions;
            OneAxisInputControl[] controls={a.left,a.right,a.jump,a.attack,a.dash,a.down,a.quickCast};
            for(int i=0;i<controls.Length;i++) inputs[controls[i]]=i;
            Logger.LogInfo("Input bound");
        }
        if(Time.realtimeSinceStartup-lastContact>2f) Array.Clear(held,0,held.Length);
        if(!busy) { Request r=null; lock(requests) if(requests.Count>0) r=requests.Dequeue();
            if(r!=null) { busy=true; lastContact=Time.realtimeSinceStartup; StartCoroutine(Execute(r)); }
        }
    }
    void LateUpdate() { Array.Copy(held,previous,held.Length); }
    IEnumerator Execute(Request r) {
        try {
            if(r.text=="load") GameManager.instance.LoadGameFromUI(4);
            else if(r.text=="reset") {
                Array.Clear(held,0,held.Length); resetting=true; boss=null; maxBossHp=0; sawBoss=false; won=false;
                BossSequenceController.Reset();
                PlayerData.instance.currentBossSequence=null;
                PlayerData.instance.health=PlayerData.instance.maxHealth;
                PlayerData.instance.bossStatueTargetLevel=0;
                GameManager.instance.BeginSceneTransition(new GameManager.SceneLoadInfo { SceneName="GG_Gruz_Mother", EntryGateName="door_dreamEnter", EntryDelay=0f, Visualization=GameManager.SceneLoadVisualizations.GodsAndGlory });
            } else if(r.text.StartsWith("step ")) {
                int mask=int.Parse(r.text.Substring(5)); for(int i=0;i<7;i++) held[i]=(mask&(1<<i))!=0;
            } else if(r.text=="release") Array.Clear(held,0,held.Length);
        } catch(Exception e) { r.result="{\"error\":\""+e.GetType().Name+"\"}"; }
        if(r.text.StartsWith("step ")) for(int i=0;i<3;i++) yield return new WaitForFixedUpdate();
        if(r.result==null) { try { r.result=State(); } catch(Exception e) { r.result="{\"error\":\""+e.GetType().Name+"\"}"; Logger.LogError(e); } }
        r.done.Set(); busy=false;
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
        return string.Format(System.Globalization.CultureInfo.InvariantCulture,
            "{{\"scene\":\"{0}\",\"ready\":{1},\"won\":{2},\"hp\":{3},\"boss_hp\":{4},\"boss_max_hp\":{5},\"soul\":{6},\"x\":{7},\"y\":{8},\"vx\":{9},\"vy\":{10},\"bx\":{11},\"by\":{12},\"bvx\":{13},\"bvy\":{14},\"grounded\":{15},\"frame\":{16},\"time\":{17}}}",
            scene,ready.ToString().ToLower(),won.ToString().ToLower(),pd!=null?pd.health:0,boss!=null?boss.hp:0,maxBossHp,pd!=null?pd.MPCharge:0,p.x,p.y,v.x,v.y,b.x,b.y,bv.x,bv.y,hero!=null&&hero.cState.onGround?1:0,Time.frameCount,Time.time);
    }
    void OnDestroy() { Array.Clear(held,0,held.Length); if(listener!=null)listener.Stop(); }
}
