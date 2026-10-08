// Opt-in raw recorder. No boss-name guesses, semantic FSM mapping or rewards.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using HarmonyLib;
using UnityEngine;
using UnityEngine.SceneManagement;
using HutongGames.PlayMaker;

public static class FalseKnightAudit {
    static bool enabled,overflow;
    static int epoch,sceneHandle,sequence;
    static readonly List<string> events=new List<string>();
    static readonly Dictionary<Fsm,string> fsmOwners=new Dictionary<Fsm,string>();
    static BossSceneController controller;
    public static void PhysicsSample(int tick,int mask){
        if(!enabled)return;Sample();
        var hero=HeroController.instance;var pd=PlayerData.instance;
        Record("physics_boundary",",\"tick\":"+tick+",\"input_mask\":"+mask+",\"hero_hp\":"+(pd==null?-1:pd.health)+",\"x\":"+(hero==null?"null":hero.transform.position.x.ToString("R",CultureInfo.InvariantCulture))+",\"y\":"+(hero==null?"null":hero.transform.position.y.ToString("R",CultureInfo.InvariantCulture)));
    }
    static string Q(string s){return "\""+(s??"").Replace("\\","\\\\").Replace("\"","\\\"").Replace("\n","\\n").Replace("\r","\\r").Replace("\t","\\t")+"\"";}
    static string Actor(HealthManager h){return ReferenceEquals(h,null)?"null":h.GetInstanceID().ToString();}
    static void Record(string kind,string details){
        if(!enabled)return;
        if(events.Count>=100000){overflow=true;return;}
        events.Add("{\"seq\":"+(++sequence)+",\"epoch\":"+epoch+",\"frame\":"+Time.frameCount+",\"fixed_time\":"+Time.fixedTimeAsDouble.ToString("R",CultureInfo.InvariantCulture)+",\"kind\":"+Q(kind)+details+"}");
    }
    public static void Install(Harmony harmony){
        // Native transitions bypass SetState; EnterState covers their action entry.
        harmony.Patch(AccessTools.Method(typeof(Fsm),"EnterState",new Type[]{typeof(FsmState)}),new HarmonyMethod(typeof(FalseKnightAudit),"StateEntered"));
        harmony.Patch(AccessTools.Method(typeof(HealthManager),"TakeDamage"),new HarmonyMethod(typeof(FalseKnightAudit),"BeforeHit"),new HarmonyMethod(typeof(FalseKnightAudit),"AfterHit"));
        // Postfix confirms Die executed, rather than treating its invocation as a kill.
        harmony.Patch(AccessTools.Method(typeof(HealthManager),"Die"),null,new HarmonyMethod(typeof(FalseKnightAudit),"Died"));
        harmony.Patch(AccessTools.Method(typeof(PlayerData),"TakeHealth"),new HarmonyMethod(typeof(FalseKnightAudit),"BeforeHurt"),new HarmonyMethod(typeof(FalseKnightAudit),"AfterHurt"));
    }
    static void StateEntered(Fsm __instance,FsmState __0){
        if(!enabled)return;string identity;
        if(!fsmOwners.TryGetValue(__instance,out identity))identity="UNREGISTERED";
        Record("fsm_entry",",\"fsm\":"+Q(identity)+",\"state\":"+Q(__0==null?"":__0.Name));
    }
    static void BeforeHit(HealthManager __instance,out int __state){__state=__instance.hp;}
    static void AfterHit(HealthManager __instance,int __state){
        if(!enabled)return;
        Record("health_damage_call",",\"actor\":"+Actor(__instance)+",\"hp_before\":"+__state+",\"hp_after\":"+__instance.hp);
    }
    static void Died(HealthManager __instance){Record("native_death",",\"actor\":"+Actor(__instance));}
    static void BeforeHurt(PlayerData __instance,out int __state){__state=__instance.health;}
    static void AfterHurt(PlayerData __instance,int __state){Record("hero_health_call",",\"hp_before\":"+__state+",\"hp_after\":"+__instance.health);}
    static void Complete(){Record("scene_complete","");}
    static void BossesDead(){Record("bosses_dead","");}
    static void Disconnect(){if(controller!=null){controller.OnBossesDead-=BossesDead;controller.OnBossSceneComplete-=Complete;}controller=null;}
    static string Snapshot(){
        var scene=UnityEngine.SceneManagement.SceneManager.GetActiveScene();var rows=new List<string>();
        foreach(var h in Resources.FindObjectsOfTypeAll<HealthManager>())if(h.gameObject.scene==scene){
            var states=new List<string>();foreach(var f in h.GetComponents<PlayMakerFSM>())states.Add("{\"name\":"+Q(f.FsmName)+",\"state\":"+Q(f.ActiveStateName)+"}");
            rows.Add("{\"actor\":"+Actor(h)+",\"name\":"+Q(h.name)+",\"hp\":"+h.hp+",\"active\":"+(h.gameObject.activeInHierarchy?"true":"false")+",\"x\":"+h.transform.position.x.ToString("R",CultureInfo.InvariantCulture)+",\"y\":"+h.transform.position.y.ToString("R",CultureInfo.InvariantCulture)+",\"states\":["+string.Join(",",states.ToArray())+"]}");
        }
        return "{\"scene\":"+Q(scene.name)+",\"frame\":"+Time.frameCount+",\"fixed_time\":"+Time.fixedTimeAsDouble.ToString("R",CultureInfo.InvariantCulture)+",\"actors\":["+string.Join(",",rows.ToArray())+"]}";
    }
    public static void Sample(){
        if(!enabled)return;
        var scene=UnityEngine.SceneManagement.SceneManager.GetActiveScene();
        if(scene.handle!=sceneHandle){Record("scene_changed",",\"scene\":"+Q(scene.name));enabled=false;Disconnect();return;}
        if(controller==null && BossSceneController.Instance!=null){controller=BossSceneController.Instance;controller.OnBossesDead+=BossesDead;controller.OnBossSceneComplete+=Complete;Record("controller_attached","");}
    }
    public static string Command(string command){
        if(command=="snapshot")return Snapshot();
        if(command=="start"){
            Disconnect();events.Clear();fsmOwners.Clear();epoch++;sequence=0;overflow=false;
            var scene=UnityEngine.SceneManagement.SceneManager.GetActiveScene();sceneHandle=scene.handle;enabled=true;
            foreach(var p in Resources.FindObjectsOfTypeAll<PlayMakerFSM>())if(p.gameObject.scene==scene){
                string id=p.gameObject.GetInstanceID()+":"+p.FsmName;fsmOwners[p.Fsm]=id;
                Record("fsm_inventory",",\"fsm\":"+Q(id)+",\"name\":"+Q(p.name)+",\"state\":"+Q(p.ActiveStateName));
            }
            foreach(var h in Resources.FindObjectsOfTypeAll<HealthManager>())if(h.gameObject.scene==scene)Record("actor_inventory",",\"actor\":"+Actor(h)+",\"name\":"+Q(h.name)+",\"hp\":"+h.hp);
            Record("capture_start",",\"scene\":"+Q(scene.name));Sample();
        }else if(command=="stop"){Record("capture_stop","");enabled=false;Disconnect();}
        else if(command!="read")throw new ArgumentException("Unknown audit command");
        return "{\"schema\":\"false-knight-raw-audit-v1\",\"enabled\":"+(enabled?"true":"false")+",\"overflow\":"+(overflow?"true":"false")+",\"semantic_validation\":false,\"events\":["+string.Join(",",events.ToArray())+"]}";
    }
}
