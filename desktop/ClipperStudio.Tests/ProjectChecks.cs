using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using ClipperStudio.Engine;

static class ProjectChecks
{
    public static async Task Run(string url, string sample, Action<bool,string> check)
    {
        using var http = new HttpClient { BaseAddress = new Uri(url) };
await TestSession.Open(http);
        async Task<JsonNode> Get(string path) => (await http.GetFromJsonAsync<JsonNode>(path))!;
        check((await http.PostAsJsonAsync("/api/projects", new { name=" " })).StatusCode == HttpStatusCode.BadRequest,"Empty project names must fail.");
        var response = await http.PostAsJsonAsync("/api/projects", new { name="Proyecto de prueba", description="API" });
        check(response.IsSuccessStatusCode,"Project creation failed.");
        var project = (await response.Content.ReadFromJsonAsync<JsonNode>())!;
        string id=J.S(project["id"]);
        using(var upload=new MultipartFormDataContent())
        {
            upload.Add(new StringContent("Private project resource"),"file","brief.txt");
            var uploaded=await http.PostAsync($"/api/projects/{id}/resources",upload);
            check(uploaded.IsSuccessStatusCode,"Project resource upload failed.");
            var resource=(await uploaded.Content.ReadFromJsonAsync<JsonNode>())!;
            check(J.S(resource["project_id"])==id,"Resources must retain their project membership.");
            check((await http.GetAsync($"/api/projects/{Store.DefaultProject}/resources/{J.S(resource["id"])}/file")).StatusCode==HttpStatusCode.NotFound,"Another project must not access the resource.");
            check(await http.GetStringAsync($"/api/projects/{id}/resources/{J.S(resource["id"])}/file")=="Private project resource","Resource download must preserve contents.");
            check(J.Items(await Get($"/api/projects/{Store.DefaultProject}/resources")).Count()==0,"Resource lists must remain isolated.");
        }
        foreach(var kind in new[]{"sources","jobs","clips","queue"}) check(J.Items(await Get($"/api/{kind}?project_id={id}")).Count()==0,"New projects must start empty.");
        response=await http.PostAsJsonAsync("/api/sources/from-path",new{path=sample,rights="own",evidence="Synthetic project fixture",project_id=id});
        check(response.IsSuccessStatusCode,"Registering inside a project failed.");
        var source=(await response.Content.ReadFromJsonAsync<JsonNode>())!;
        string sourceId=J.S(source["id"]);
        check(J.S(source["project_id"])==id,"Registered sources must retain project membership.");
        response=await http.PostAsJsonAsync($"/api/sources/{sourceId}/clip",new{start=0,duration=3});
        check(response.IsSuccessStatusCode,"Manual clip creation in a project failed.");
        var clip=(await response.Content.ReadFromJsonAsync<JsonNode>())!;
        clip = await Get($"/api/clips/{J.S(clip["id"])}");
        check(J.S(clip["project_id"])==id,"Manual clips must inherit the source project.");
        check((await http.PutAsJsonAsync($"/api/sources/{sourceId}/project",new{project_id="missing"})).StatusCode==HttpStatusCode.NotFound,"Moving to an unknown project must fail.");
        check((await http.PutAsJsonAsync($"/api/sources/{sourceId}/project",new{project_id=Store.DefaultProject})).IsSuccessStatusCode,"Moving a source failed.");
        check(J.Items(await Get($"/api/clips?project_id={id}")).Count()==0,"Moved clips must leave their old project.");
        check(J.S((await Get($"/api/clips/{J.S(clip["id"])}"))["project_id"])==Store.DefaultProject,"Clips must move with the source.");
        check((await http.PutAsJsonAsync("/api/settings",new{device="cpu"})).IsSuccessStatusCode,"CPU selection failed.");
        check(J.S((await Get("/api/config"))["render"]?["resolved_encoder"])=="libx264","CPU selection must override automatic GPU preference.");
        check((await http.PutAsJsonAsync("/api/settings",new{device="dxgi:9999"})).StatusCode==HttpStatusCode.BadRequest,"Unknown devices must fail validation.");
        check(Hw.Chain("libx264").SequenceEqual(new[]{"libx264"}),"Explicit CPU must never fall back to a GPU.");
        Console.WriteLine("Detected devices: " + Hw.DeviceList().ToJsonString());
    }
}
