using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using ClipperStudio.Engine;
using ClipperStudio.Server;

static class LocaleChecks
{
    public static async Task Run(Api api, Action<bool,string> check)
    {
        using var http=new HttpClient {BaseAddress=new Uri(api.Url)};
        await TestSession.Open(http);
        var before=await http.GetFromJsonAsync<JsonObject>("/api/config");
        var languages=before!["languages"]?.ToJsonString();
        check(UiText.Preference=="en","Native UI must default to English.");
        foreach(var language in UiText.Languages)
        {
            var response=await http.PutAsJsonAsync("/api/settings/ui-language",new{language});
            check(response.IsSuccessStatusCode && UiText.Preference==language,"Native UI preference must persist in each supported language.");
            check(UiText.Get("Mover",language)!= "Mover" || language is "es" or "pt","Native text must use the shared locale catalog.");
            check(!string.IsNullOrWhiteSpace(UiText.Get("Preparando FFmpeg y la GPU…",language)),"Startup translation missing.");
            var after=await http.GetFromJsonAsync<JsonObject>("/api/config");
            check(after!["languages"]?.ToJsonString()==languages,"UI language must never change video generation languages.");
        }
        check((await http.PutAsJsonAsync("/api/settings/ui-language",new{language="xx"})).StatusCode==HttpStatusCode.BadRequest,"Unknown UI locales must be rejected.");
        check(UiText.Preference=="de","Rejected locale must retain previous preference.");
        string? received=null;
        api.SelectOutputFolder=language=>{received=language;return Task.FromResult<string?>(null);};
        using(var request=new HttpRequestMessage(HttpMethod.Post,"/api/setup/folder"))
        {
            request.Headers.Add("X-Kairos-Language","fr");
            check((await http.SendAsync(request)).IsSuccessStatusCode && received=="fr","Native folder chooser must receive the browser UI language.");
        }
        check((await http.PostAsync("/api/setup/folder",null)).IsSuccessStatusCode && received=="de","Folder chooser must fall back to saved UI language.");
        api.SelectOutputFolder=null;UiText.Preference="en";
    }
}
