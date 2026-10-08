// Hornet-only observation and event accounting. Never injects combat damage.
using System;
using System.Globalization;
using System.Collections.Generic;
using HarmonyLib;
using UnityEngine;
using UnityEngine.SceneManagement;
using HutongGames.PlayMaker;

public static class HornetTelemetry {
    static readonly CultureInfo CI=CultureInfo.InvariantCulture;
    static HealthManager boss;
    static BossSceneController controller;
    static int scene=-1,epoch,maxHp,damage,hurt,hits,attacks,deathId,bossId,sequence;
    static bool bossesDead,complete,armed;
    static string opening="native";
    static bool openingApplied=true;
    static string phase="";
    static double phaseAt;
    static readonly List<string> journal=new List<string>();
    public static bool IsEncounter {get{return UnityEngine.SceneManagement.SceneManager.GetActiveScene().name=="GG_Hornet_1";}}
    static string Q(string s){return "\""+(s??"").Replace("\\","\\\\").Replace("\"","\\\"").Replace("\n","\\n").Replace("\r","\\r")+"\"";}
    static string N(double n){return n.ToString("R",CI);}
    static void Event(string kind,int amount){journal.Add("{\"seq\":"+(++sequence)+",\"frame\":"+Time.frameCount+",\"time\":"+N(Time.fixedTimeAsDouble)+",\"kind\":"+Q(kind)+",\"amount\":"+amount+"}");}
    static void Dead(){bossesDead=true;Event("bosses_dead",0);}
    static void Complete(){complete=true;Event("scene_complete",0);}
    static void Configure(BossSceneController c){c.BossLevel=0;BossSceneController.SetupEvent-=Configure;}
    public static void Reset(string requestedOpening="native"){
        if(requestedOpening!="native" && requestedOpening!="near-left" && requestedOpening!="near-right")throw new ArgumentException("Unknown opening");
        opening=requestedOpening;openingApplied=opening=="native";
        armed=false;
        var p=PlayerData.instance;
        BossSequenceController.Reset();p.currentBossSequence=null;
        p.maxHealth=p.health=9;p.healthBlue=0;p.MPCharge=0;
        p.nailDamage=9;p.nailSmithUpgrades=1;
        p.hasDash=true;p.hasShadowDash=false;p.hasDoubleJump=false;p.hasWalljump=true;
        p.infiniteAirJump=false;p.hasNailArt=false;
        p.hasDashSlash=p.hasUpwardSlash=p.hasCyclone=false;
        p.fireballLevel=p.quakeLevel=p.screamLevel=0;
        for(int i=1;i<=40;i++){var f=AccessTools.Field(typeof(PlayerData),"equippedCharm_"+i);if(f!=null)f.SetValue(p,false);}
        p.bossStatueTargetLevel=0;
        BossSceneController.SetupEvent-=Configure;BossSceneController.SetupEvent+=Configure;
        GameManager.instance.BeginSceneTransition(new GameManager.SceneLoadInfo{SceneName="GG_Hornet_1",EntryGateName="door_dreamEnter",EntryDelay=0f,Visualization=GameManager.SceneLoadVisualizations.GodsAndGlory});
    }
    public static void Install(Harmony h){
        h.Patch(AccessTools.Method(typeof(HealthManager),"TakeDamage"),new HarmonyMethod(typeof(HornetTelemetry),"BeforeDamage"),new HarmonyMethod(typeof(HornetTelemetry),"AfterDamage"));
        h.Patch(AccessTools.Method(typeof(HealthManager),"Die"),null,new HarmonyMethod(typeof(HornetTelemetry),"Died"));
        h.Patch(AccessTools.Method(typeof(PlayerData),"TakeHealth"),new HarmonyMethod(typeof(HornetTelemetry),"BeforeHurt"),new HarmonyMethod(typeof(HornetTelemetry),"AfterHurt"));
        h.Patch(AccessTools.Method(typeof(HeroController),"Attack"),null,new HarmonyMethod(typeof(HornetTelemetry),"Attack"));
        h.Patch(AccessTools.Method(typeof(Fsm),"EnterState",new Type[]{typeof(FsmState)}),null,new HarmonyMethod(typeof(HornetTelemetry),"Entered"));
    }
    static void Entered(Fsm __instance,FsmState __0){
        if(!armed || boss==null)return;
        foreach(var f in boss.GetComponents<PlayMakerFSM>())if(f.FsmName=="Control" && f.Fsm==__instance){phase=__0.Name;phaseAt=Time.fixedTimeAsDouble;Event("fsm:"+phase,0);}
    }
    static void BeforeDamage(HealthManager __instance,out int __state){__state=armed && __instance==boss?Math.Max(0,__instance.hp):-1;}
    static void AfterDamage(HealthManager __instance,int __state){
        if(__state<0)return;
        int amount=deathId==bossId?__state:Math.Max(0,Math.Min(__state,__state-__instance.hp));
        if(amount>0){damage+=amount;hits++;Event("damage",amount);}
    }
    static void Died(HealthManager __instance){if(armed && __instance.GetInstanceID()==bossId){deathId=bossId;Event("health_manager_die_completed",0);}}
    static void BeforeHurt(PlayerData __instance,out int __state){__state=armed?__instance.health:-1;}
    static void AfterHurt(PlayerData __instance,int __state){if(__state>=0){int amount=Math.Max(0,__state-__instance.health);if(amount>0){hurt+=amount;Event("hurt",amount);}}}
    static void Attack(){if(armed){attacks++;Event("attack",0);}}
    public static void Sample(){
        if(!IsEncounter){armed=false;return;}
        int now=UnityEngine.SceneManagement.SceneManager.GetActiveScene().handle;
        if(now!=scene){
            if(controller!=null){controller.OnBossesDead-=Dead;controller.OnBossSceneComplete-=Complete;}
            scene=now;epoch++;boss=null;controller=null;maxHp=damage=hurt=hits=attacks=deathId=bossId=sequence=0;
            bossesDead=complete=armed=false;journal.Clear();phase="";
        }
        if(controller==null && BossSceneController.Instance!=null){controller=BossSceneController.Instance;controller.OnBossesDead+=Dead;controller.OnBossSceneComplete+=Complete;}
        if(bossId==0 && controller!=null && controller.bosses!=null){
            var found=new List<HealthManager>();
            foreach(var candidate in controller.bosses)if(candidate!=null && candidate.gameObject.scene.handle==scene)found.Add(candidate);
            if(found.Count==1){boss=found[0];bossId=boss.GetInstanceID();maxHp=boss.hp;armed=true;Event("registered",maxHp);}
        }
        if(armed && !openingApplied && boss!=null && HeroController.instance!=null){
            var hero=HeroController.instance;var hb=hero.GetComponent<Rigidbody2D>();var bb=boss.GetComponent<Rigidbody2D>();
            if(hb!=null && bb!=null && hero.cState.onGround && Math.Abs(bb.linearVelocity.y)<.1f && Math.Abs(boss.transform.position.y-hero.transform.position.y)<1.5f && PlayerData.instance.health==9 && hurt==0 && damage==0){
                var c=hero.GetComponent<Collider2D>();var dest=hero.transform.position;dest.x=boss.transform.position.x+(opening=="near-left"?-4.5f:4.5f);
                Vector2 center=(Vector2)dest+(Vector2)(c.bounds.center-hero.transform.position);int layer=LayerMask.NameToLayer("Terrain");
                var floor=Physics2D.Raycast(center,Vector2.down,3f,1<<layer);
                if(layer<0 || floor.collider==null || Physics2D.OverlapBox(center,c.bounds.size*.95f,0f,1<<layer)!=null)throw new InvalidOperationException("Unsafe opening geometry");
                var face=AccessTools.Method(typeof(HeroController),opening=="near-left"?"FaceRight":"FaceLeft");
                if(face==null)throw new InvalidOperationException("Missing native facing method");
                hero.transform.position=dest;hb.position=dest;hb.linearVelocity=Vector2.zero;face.Invoke(hero,null);Physics2D.SyncTransforms();openingApplied=true;Event("opening:"+opening,0);
            }
        }
    }
    public static string State(){
        Sample();var b=boss!=null?boss.transform.position:Vector3.zero;var rb=boss!=null?boss.GetComponent<Rigidbody2D>():null;var v=rb!=null?rb.linearVelocity:Vector2.zero;
        var names=new List<string>();if(boss!=null)foreach(var f in boss.GetComponents<PlayMakerFSM>())if(f.FsmName=="Control"){
            foreach(var state in f.FsmStates)names.Add(state.Name);
            if(phase==""){phase=f.ActiveStateName;phaseAt=Time.fixedTimeAsDouble;}
        }
        names.Sort(StringComparer.Ordinal);var quoted=names.ConvertAll(Q);
        string e=string.Join(",",journal.ToArray());journal.Clear();
        return "{\"opening\":"+Q(opening)+",\"opening_applied\":"+(openingApplied?"true":"false")+",\"schema\":\"hornet-v1\",\"epoch\":"+epoch+",\"actor\":"+bossId+",\"valid\":"+(boss!=null?"true":"false")+",\"max_hp\":"+maxHp+",\"hp\":"+(boss!=null?boss.hp:0)+",\"x\":"+N(b.x)+",\"y\":"+N(b.y)+",\"vx\":"+N(v.x)+",\"vy\":"+N(v.y)+",\"phase\":"+Q(phase)+",\"phase_age\":"+N(Time.fixedTimeAsDouble-phaseAt)+",\"phase_names\":["+string.Join(",",quoted.ToArray())+"],\"damage\":"+damage+",\"hurt\":"+hurt+",\"hits\":"+hits+",\"attacks\":"+attacks+",\"native_death\":"+(deathId!=0?"true":"false")+",\"bosses_dead\":"+(bossesDead?"true":"false")+",\"complete\":"+(complete?"true":"false")+",\"nail_damage\":"+PlayerData.instance.nailDamage+",\"events\":["+e+"]}";
    }
}
