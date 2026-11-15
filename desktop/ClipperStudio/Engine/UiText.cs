using System.Text.Json.Nodes;

namespace ClipperStudio.Engine;

/// <summary>Native window text uses the same catalog as the shared web UI. Never used for video content.</summary>
public static class UiText
{
    public static readonly string[] Languages = ["en","es","pt","fr","de"];
    static Dictionary<string,string[]>? _catalog;
    static readonly string PreferenceFile=Path.Combine(Paths.Data,"ui-language.json");
    public static string Preference
    {
        get {try{var language=J.S(JsonNode.Parse(File.ReadAllText(PreferenceFile))?["language"]);return Languages.Contains(language)?language:"en";}catch{return "en";}}
        set {
            if(!Languages.Contains(value))throw new EditException("Unsupported interface language");
            var temporary=PreferenceFile+".tmp";
            File.WriteAllText(temporary,new JsonObject{["language"]=value}.ToJsonString());File.Move(temporary,PreferenceFile,true);
        }
    }
    public static string Get(string source,string? language=null)
    {
        _catalog ??= File.ReadLines(Path.Combine(Paths.Web,"locales.tsv")).Select(l=>l.Split('\t')).Where(a=>a.Length==5).GroupBy(a=>a[0]).ToDictionary(g=>g.Key,g=>g.Last());
        int index=Array.IndexOf(new[]{"es","en","pt","fr","de"},language??Preference);
        return _catalog.TryGetValue(source,out var values)?values[index<0?1:index]:source;
    }
}
