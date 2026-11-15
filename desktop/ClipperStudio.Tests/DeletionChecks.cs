using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using ClipperStudio.Engine;

static class DeletionChecks
{
    public static async Task Run(string url,Action<bool,string> check)
    {
        using var client=new HttpClient{BaseAddress=new Uri(url)};
        check((await client.GetAsync("/api/settings/ai")).StatusCode==HttpStatusCode.Unauthorized,"Anonymous clients must not read the API.");
        var page=await client.GetAsync("/");
        check(page.Headers.GetValues("Set-Cookie").Any(v=>v.Contains("httponly",StringComparison.OrdinalIgnoreCase)&&v.Contains("samesite=strict",StringComparison.OrdinalIgnoreCase)),"Session cookie must be HttpOnly and SameSite Strict.");
        check((await client.PostAsJsonAsync("/api/projects",new{name="blocked"})).StatusCode==HttpStatusCode.Forbidden,"A cookie alone must not permit mutations.");
        await TestSession.Open(client);
        check(AiSettings.CredentialTransportError("http://remote.example/v1","secret")!=null,"Remote HTTP must not receive API keys.");
        check(AiSettings.CredentialTransportError("http://127.0.0.1:11434/v1","secret")==null,"Local model servers must remain supported.");
        check(AiSettings.CredentialTransportError("https://remote.example/v1","secret")==null,"HTTPS providers must remain supported.");
        string? previousKey=Environment.GetEnvironmentVariable("OPENAI_API_KEY");
        const string secret="private-test-key-never-return-this-value";
        try
        {
            Environment.SetEnvironmentVariable("OPENAI_API_KEY",secret);
            check(!(await client.GetStringAsync("/api/settings/ai")).Contains(secret),"Provider settings must never return the full API key.");
            var response=await client.PostAsJsonAsync("/api/projects",new{name="Redaction test",description=secret});
            string text=await response.Content.ReadAsStringAsync();
            check(response.IsSuccessStatusCode && !text.Contains(secret) && text.Contains("[REDACTED]"),"API JSON must redact configured secrets even when echoed by another field.");
            string id=J.S(JsonNode.Parse(text)?["id"]);
            check((await client.DeleteAsync("/api/library/projects/"+id)).IsSuccessStatusCode,"Project deletion route must accept a valid session.");
        }
        finally{Environment.SetEnvironmentVariable("OPENAI_API_KEY",previousKey);}
        using(var request=new HttpRequestMessage(HttpMethod.Get,"/api/settings/ai"))
        {request.Headers.Add("Origin","https://untrusted.example");check((await client.SendAsync(request)).StatusCode==HttpStatusCode.Forbidden,"External websites must not read local credentials.");}
        using(var request=new HttpRequestMessage(HttpMethod.Get,"/api/config"))
        {request.Headers.Host="untrusted.example";check((await client.SendAsync(request)).StatusCode==HttpStatusCode.Forbidden,"DNS rebinding hosts must be rejected.");}
        var store=new Store();
        string project="project_delete_test",other="project_delete_other";
        foreach(var id in new[]{project,other})store.Add("projects",new JsonObject{["id"]=id,["name"]=id});
        string owned=Path.Combine(Paths.Dir("downloads",project),"managed.mp4"),external=Path.Combine(Paths.Data,"external-original.mp4");
        File.WriteAllText(owned,"owned");File.WriteAllText(external,"keep");
        store.Add("sources",new JsonObject{["id"]="src_delete",["project_id"]=project,["path"]=owned});
        store.Add("sources",new JsonObject{["id"]="src_external",["project_id"]=project,["path"]=external});
        store.Add("sources",new JsonObject{["id"]="src_keep",["project_id"]=other,["path"]="keep.mp4"});
        store.Add("jobs",new JsonObject{["id"]="job_delete",["project_id"]=project,["source_id"]="src_delete",["status"]="done"});
        string package=Path.Combine(store.OutputRoot,"clip_delete");Directory.CreateDirectory(package);File.WriteAllText(Path.Combine(package,"clip.mp4"),"generated");
        store.Add("clips",new JsonObject{["id"]="clip_delete",["project_id"]=project,["job_id"]="job_delete",["package_dir"]=package});
        string resource=Path.Combine(Paths.Dir("projects",project,"resources"),"res_delete.txt");File.WriteAllText(resource,"reference");
        store.Add("resources",new JsonObject{["id"]="res_delete",["project_id"]=project,["extension"]=".txt"});
        // The API holds its own in-memory Store; validate the same deletion implementation directly.
        var removed=store.DeleteLibrary("projects",project);
        check(J.D(removed["removed"]?["clips"])==1 && J.D(removed["removed"]?["sources"])==2,"Project deletion must cascade to its own clips and sources.");
        check(store.Get("projects",other)!=null&&store.Get("sources","src_keep")!=null,"Deleting a project must preserve other projects.");
        check(File.Exists(external)&&!File.Exists(owned)&&!Directory.Exists(package)&&!File.Exists(resource),"Managed files must be quarantined and external originals preserved.");
        check(Directory.GetFiles(Paths.Dir("trash"),"manifest.json",SearchOption.AllDirectories).Length>0,"Deletion must retain recovery records.");
        check((await client.DeleteAsync("/api/library/projects/project_default")).StatusCode==HttpStatusCode.BadRequest,"The default project must remain available.");
        check((await client.DeleteAsync("/api/library/clips/missing")).StatusCode==HttpStatusCode.NotFound,"Unknown shorts must return 404.");
    }
}
