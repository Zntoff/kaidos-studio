using System.Text.Json.Nodes;
using ClipperStudio.Engine;

internal static class Preview
{
    // Render an isolated short copy for visual QA. Never write to the person's actual library or package.
    public static void Render(string libraryPath, string clipId, string layout)
    {
        var db = JsonNode.Parse(File.ReadAllText(libraryPath))!;
        var original = J.Items(db["clips"]).Single(c => J.S(c["id"]) == clipId);
        var clip = (JsonObject)J.Clone(original);
        var edl = (JsonObject)J.Clone(clip["draft"]?["edl"] ?? clip["edl"]!);
        var tracks = J.Clone(clip["draft"]?["tracks"] ?? clip["tracks"]!);
        var source = (JsonObject)J.Clone(J.Items(db["sources"]).Single(s => J.S(s["id"]) == J.S(edl["source"]!["id"])));
        edl["source"]!["end"] = Math.Min(J.D(edl["source"]!["end"]), J.D(edl["source"]!["start"]) + 8);
        edl["layout"] = layout;
        double duration = Renderer.Duration(edl);
        foreach (var key in new[] { "effects", "texts" })
            edl[key] = new JsonArray(J.Items(edl[key]).Where(x => J.D(x["t"]) < duration).Select(J.Clone).ToArray());
        clip["id"] = "qa_" + Guid.NewGuid().ToString("N")[..8]; edl["clip_id"] = J.S(clip["id"]);
        clip["status"] = "needs_human"; clip["package_dir"] = null;
        clip["edl"] = J.Clone(edl); clip["tracks"] = J.Clone(tracks);
        clip["draft"] = new JsonObject { ["edl"] = edl, ["tracks"] = tracks };
        var store = new Store();
        store.Add("sources", source); store.Add("clips", clip);
        store.Settings = new RenderSettings { Encoder = "libx264", GpuDecode = false, Quality = 24 };
        var result = new EditorSvc(store).RenderDraft(J.S(clip["id"]), _ => { });
        Console.WriteLine(J.S(result["dir"]));
    }
}
