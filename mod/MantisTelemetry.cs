// Read-only telemetry. Raw FSM labels require a live encounter audit before training.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using HarmonyLib;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class MantisTelemetry {
    static readonly CultureInfo CI=CultureInfo.InvariantCulture;
    static readonly Dictionary<int,HealthManager> actors=new Dictionary<int,HealthManager>();
    static readonly Dictionary<int,string> signatures=new Dictionary<int,string>();
    static readonly Dictionary<int,double> changedAt=new Dictionary<int,double>();
    class Identity { public string name;public int gameObjectId;public Vector3 position; }
    static readonly Dictionary<int,Identity> identities=new Dictionary<int,Identity>();
    static readonly HashSet<int> deadActors=new HashSet<int>();
    static BossSceneController controller;
    static int sceneHandle=-1,epoch,hurt,healed,damage,nailDamage,quakeDamage,hits;
    static bool bossesDead,sceneComplete;
    static bool diagnosticSession;
    static int lastHitActor;
    static string lastDamageSource="";
    public struct IncomingContext { public string source;public int hazardType; }
    static IncomingContext incoming;
    static int spikeHurt,bossHurt,unknownHurt;
    static string lastHurtSource="";
    static readonly Dictionary<string,int> spellSources=new Dictionary<string,int>();
    static float nextDiscovery;
    public static bool IsEncounter {
        get { string n=UnityEngine.SceneManagement.SceneManager.GetActiveScene().name;return n=="GG_Mantis_Lords" || n=="GG_Mantis_Lords_V"; }
    }
    static string Q(string s) {
        var b=new StringBuilder("\"");
        foreach(char c in s??"") {
            if(c=='\\')b.Append("\\\\");else if(c=='\"')b.Append("\\\"");
            else if(c<' ')b.Append("\\u"+((int)c).ToString("x4"));else b.Append(c);
        }
        return b.Append('"').ToString();
    }
    static double Clock { get { return Time.fixedTimeAsDouble; } }
    static bool IsMantis(HealthManager h) {
        if(h==null || !h.enabled || h.gameObject.GetComponent<HealthManager>()!=h || h.gameObject.scene!=UnityEngine.SceneManagement.SceneManager.GetActiveScene())return false;
        string name=h.name.ToLowerInvariant();return name.Contains("mantis") && name.Contains("lord");
    }
    static void OnDead(){bossesDead=true;}
    static void OnComplete(){sceneComplete=true;}
    public static void Sample() {
        if(!IsEncounter)return;
        int current=UnityEngine.SceneManagement.SceneManager.GetActiveScene().handle;
        if(current!=sceneHandle) {
            if(controller!=null){controller.OnBossesDead-=OnDead;controller.OnBossSceneComplete-=OnComplete;}
            controller=null;sceneHandle=current;epoch++;actors.Clear();signatures.Clear();changedAt.Clear();
            identities.Clear();deadActors.Clear();
            hurt=healed=damage=nailDamage=quakeDamage=hits=lastHitActor=0;bossesDead=sceneComplete=diagnosticSession=false;nextDiscovery=0;spellSources.Clear();lastDamageSource="";
            spikeHurt=bossHurt=unknownHurt=0;lastHurtSource="";incoming=new IncomingContext{source="",hazardType=-1};
        }
        if(controller==null && BossSceneController.Instance!=null) {
            controller=BossSceneController.Instance;controller.OnBossesDead+=OnDead;controller.OnBossSceneComplete+=OnComplete;
        }
        // Include inactive scene objects: disappearance must not change identity.
        if(Time.realtimeSinceStartup>=nextDiscovery) {
            nextDiscovery=Time.realtimeSinceStartup+0.2f;
            foreach(var h in Resources.FindObjectsOfTypeAll<HealthManager>())if(IsMantis(h))Register(h);
        }
    }
    static void Register(HealthManager h) {
        int id=h.GetInstanceID();actors[id]=h;identities[id]=new Identity{name=h.name,gameObjectId=h.gameObject.GetInstanceID(),position=h.transform.position};
    }
    public static bool BeforeHit(HealthManager h) {
        if(!IsEncounter || !IsMantis(h))return false;Sample();Register(h);return true;
    }
    public static void ActorDied(HealthManager h) {
        if(BeforeHit(h))deadActors.Add(h.GetInstanceID());
    }
    public static void BossDamage(HealthManager h,int previousHp,bool quake,bool nail,bool spell,string source,bool tracked) {
        if(!tracked || ReferenceEquals(h,null))return;
        // The native death method can destroy the Unity object before this postfix.
        // Use the captured identity and managed HP field, not Unity's overloaded null.
        int id=h.GetInstanceID();int amount=deadActors.Contains(id)?Math.Max(previousHp,0):Math.Max(0,Math.Min(Math.Max(previousHp,0),previousHp-h.hp));
        if(amount==0)return;lastHitActor=id;lastDamageSource=source;damage+=amount;hits++;if(quake)quakeDamage+=amount;if(nail)nailDamage+=amount;
        if(spell){if(!spellSources.ContainsKey(source))spellSources[source]=0;spellSources[source]+=amount;}
    }
    public static IncomingContext BeginIncoming(GameObject source,int hazardType) {
        Sample();var previous=incoming;string name="";
        for(Transform t=source!=null?source.transform:null;t!=null;t=t.parent)name=t.name+(name.Length>0?"/"+name:"");
        incoming=new IncomingContext{source=name,hazardType=hazardType};return previous;
    }
    public static void EndIncoming(IncomingContext previous){incoming=previous;}
    public static void HeroHealth(int lost,int gained){if(IsEncounter){
        Sample();int amount=Math.Max(lost,0);hurt+=amount;healed+=Math.Max(gained,0);
        if(amount>0){lastHurtSource=incoming.source??"";string source=lastHurtSource.ToLowerInvariant();
            if(source.Contains("spike"))spikeHurt+=amount;
            else if(source.Contains("mantis"))bossHurt+=amount;
            else unknownHurt+=amount;
        }
    }}
    // Integration test only. Never part of policy actions or performance evaluation.
    public static void DiagnosticDefeatActive() {
        Sample();diagnosticSession=true;
        var snapshot=new List<HealthManager>(actors.Values);
        foreach(var h in snapshot)if(IsMantis(h) && h.gameObject.activeInHierarchy && h.hp>0 && !(bool)AccessTools.Field(typeof(HealthManager),"invincible").GetValue(h))
            AccessTools.Method(typeof(HealthManager),"TakeDamage").Invoke(h,new object[]{new HitInstance{Source=HeroController.instance.gameObject,AttackType=AttackTypes.Nail,DamageDealt=100000,IgnoreInvulnerable=true,Multiplier=1f,MagnitudeMultiplier=0f}});
    }
    static string Box(Collider2D c) {
        Bounds b=c.bounds;return string.Format(CI,"\"cx\":{0},\"cy\":{1},\"ex\":{2},\"ey\":{3}",b.center.x,b.center.y,b.extents.x,b.extents.y);
    }
    public static string State() {
        Sample();var scene=UnityEngine.SceneManagement.SceneManager.GetActiveScene();var pd=PlayerData.instance;var hero=HeroController.instance;
        var b=new StringBuilder("{\"schema\":\"mantis-telemetry-v1\",\"scene\":"+Q(scene.name));
        b.Append(",\"scene_epoch\":"+epoch+",\"time\":"+Clock.ToString(CI));
        b.Append(",\"diagnostic_session\":"+(diagnosticSession?"true":"false"));
        b.Append(",\"encounter\":"+(IsEncounter?"true":"false")+",\"boss_level\":"+(controller!=null?controller.BossLevel:-1));
        b.Append(",\"completion_hook_attached\":"+(controller!=null?"true":"false")+",\"bosses_dead_event\":"+(bossesDead?"true":"false")+",\"scene_complete_event\":"+(sceneComplete?"true":"false"));
        b.Append(",\"win_confirmed\":"+(IsEncounter && bossesDead && pd!=null && pd.health>0?"true":"false"));
        b.Append(",\"hp\":"+(pd!=null?pd.health:0)+",\"max_hp\":"+(pd!=null?pd.maxHealth:0)+",\"soul\":"+(pd!=null?pd.MPCharge:0));
        b.Append(",\"hero_damage_taken\":"+hurt+",\"hero_healed\":"+healed+",\"damage_dealt\":"+damage+",\"effective_hits\":"+hits+",\"nail_damage\":"+nailDamage+",\"quake_damage\":"+quakeDamage);
        b.Append(",\"last_hit_actor\":"+lastHitActor);
        b.Append(",\"spike_damage_taken\":"+spikeHurt+",\"mantis_damage_taken\":"+bossHurt+",\"unknown_damage_taken\":"+unknownHurt+",\"last_hurt_source\":"+Q(lastHurtSource));
        b.Append(",\"last_damage_source\":"+Q(lastDamageSource)+",\"spell_sources\":{");bool sourceComma=false;
        foreach(var source in spellSources){if(sourceComma)b.Append(',');sourceComma=true;b.Append(Q(source.Key)+":"+source.Value);}b.Append('}');
        if(hero!=null) {
            var body=hero.GetComponent<Rigidbody2D>();var c=hero.GetComponent<Collider2D>();
            if(c!=null)b.Append(",\"hero_box\":{"+Box(c)+"}");
            b.Append(string.Format(CI,",\"hero_vx\":{0},\"hero_vy\":{1}",body!=null?body.linearVelocity.x:0,body!=null?body.linearVelocity.y:0));
            b.Append(",\"hero_invulnerable\":"+(hero.cState.invulnerable?"true":"false")+",\"hero_shadow_dashing\":"+(hero.cState.shadowDashing?"true":"false")+",\"hero_quaking\":"+(hero.cState.spellQuake?"true":"false"));
        }
        b.Append(",\"actors\":[");bool comma=false;int valid=0;
        var ids=new List<int>(actors.Keys);ids.Sort();
        foreach(int id in ids) {
            var h=actors[id];valid++;
            if(comma)b.Append(',');comma=true;
            if(h==null || deadActors.Contains(id)) {
                var identity=identities[id];var pos=identity.position;
                b.Append("{\"id\":"+id+",\"game_object_id\":"+identity.gameObjectId+",\"primary_component\":true,\"name\":"+Q(identity.name)+",\"active\":false,\"dead\":true,\"hp\":0");
                b.Append(string.Format(CI,",\"x\":{0},\"y\":{1},\"vx\":0,\"vy\":0,\"fsms\":[],\"fsm_signature_age\":0,\"colliders\":[]}}",pos.x,pos.y));continue;
            }
            var p=h.transform.position;identities[id].position=p;var body=h.GetComponent<Rigidbody2D>();
            b.Append("{\"id\":"+id+",\"game_object_id\":"+h.gameObject.GetInstanceID()+",\"primary_component\":"+(h.gameObject.GetComponent<HealthManager>()==h?"true":"false")+",\"name\":"+Q(h.name)+",\"active\":"+(h.gameObject.activeInHierarchy?"true":"false")+",\"hp\":"+h.hp);
            b.Append(string.Format(CI,",\"x\":{0},\"y\":{1},\"vx\":{2},\"vy\":{3}",p.x,p.y,body!=null?body.linearVelocity.x:0,body!=null?body.linearVelocity.y:0));
            var states=new StringBuilder();b.Append(",\"fsms\":[");bool fcomma=false;
            foreach(var f in h.GetComponentsInChildren<PlayMakerFSM>(true)) {
                if(fcomma)b.Append(',');fcomma=true;
                b.Append("{\"id\":"+f.GetInstanceID()+",\"name\":"+Q(f.FsmName)+",\"state\":"+Q(f.ActiveStateName)+"}");
                states.Append(f.GetInstanceID()+":"+f.ActiveStateName+";");
            }
            string signature=states.ToString();if(!signatures.ContainsKey(id)||signatures[id]!=signature){signatures[id]=signature;changedAt[id]=Clock;}
            b.Append("],\"fsm_signature_age\":"+(Clock-changedAt[id]).ToString(CI)+",\"colliders\":[");bool ccomma=false;
            foreach(var c in h.GetComponentsInChildren<Collider2D>(true)) {
                if(ccomma)b.Append(',');ccomma=true;b.Append("{\"id\":"+c.GetInstanceID()+",\"enabled\":"+(c.enabled&&c.gameObject.activeInHierarchy?"true":"false")+","+Box(c)+"}");
            }
            b.Append("]}");
        }
        b.Append("],\"actor_count\":"+valid+",\"actor_mapping_verified\":false,\"hazards\":[");comma=false;
        var seen=new HashSet<int>();int hazardCount=0;
        foreach(var d in UnityEngine.Object.FindObjectsOfType<DamageHero>()) {
            if(d.gameObject.scene!=scene || !d.enabled || !d.gameObject.activeInHierarchy || d.damageDealt<=0)continue;
            foreach(var c in d.GetComponentsInChildren<Collider2D>()) {
                if(!c.enabled || !c.gameObject.activeInHierarchy || c.GetComponentInParent<DamageHero>()!=d || !seen.Add(c.GetInstanceID()))continue;
                if(comma)b.Append(',');comma=true;hazardCount++;var body=c.attachedRigidbody;
                b.Append("{\"id\":"+c.GetInstanceID()+",\"name\":"+Q(c.name)+",\"source\":"+Q(d.name)+","+Box(c));
                b.Append(",\"hazard_type\":"+d.hazardType+",\"trigger\":"+(c.isTrigger?"true":"false")+",\"layer\":"+c.gameObject.layer);
                b.Append(string.Format(CI,",\"vx\":{0},\"vy\":{1},\"velocity_valid\":{2},\"configured_damage\":{3},\"shadow_hazard\":{4}}}",body!=null?body.linearVelocity.x:0,body!=null?body.linearVelocity.y:0,body!=null?"true":"false",d.damageDealt,d.shadowDashHazard?"true":"false"));
            }
        }
        // Export every hazard. A fixed-capacity policy must explicitly detect overflow.
        b.Append("],\"hazard_count\":"+hazardCount+",\"hazards_truncated\":false}");return b.ToString();
    }
}
