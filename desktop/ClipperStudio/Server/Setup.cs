using System.Text.Json.Nodes;
using ClipperStudio.Engine;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;

namespace ClipperStudio.Server;

public partial class Api
{
    void MapSetup(WebApplication app)
    {
        app.MapPost("/api/setup/folder", async (HttpRequest request) => SelectOutputFolder == null
            ? Err(501, "Puedes escribir la ruta de la carpeta manualmente.")
            : Json(new JsonObject { ["path"] = await SelectOutputFolder(request.Headers["X-Kairos-Language"].FirstOrDefault() ?? UiText.Preference) }));
        app.MapPut("/api/settings/ui-language", async (HttpRequest request) =>
        {
            var body=await JsonNode.ParseAsync(request.Body);
            string language=J.S(body?["language"]);
            if(!UiText.Languages.Contains(language))return Err(400,"Unsupported interface language");
            UiText.Preference=language;
            return Json(new JsonObject{["language"]=language});
        });
        app.MapPut("/api/setup", async (HttpRequest req) =>
        {
            var b = await JsonNode.ParseAsync(req.Body) ?? new JsonObject();
            var settings = _store.Settings;
            if (b["transcription_mode"] != null)
            {
                var mode = J.S(b["transcription_mode"]);
                if (mode is not ("fast" or "accurate")) return Err(400, "Elige transcripción rápida o precisa.");
                settings.TranscriptionMode = mode;
            }
            if (b["output_dir"] != null)
            {
                var path = J.S(b["output_dir"]).Trim();
                if (path == "" || !Path.IsPathFullyQualified(path)) return Err(400, "Elige una carpeta con una ruta completa.");
                try
                {
                    path = Path.GetFullPath(path);
                    Directory.CreateDirectory(path);
                    var probe = Path.Combine(path, ".clipper-write-test-" + Guid.NewGuid().ToString("N"));
                    using (new FileStream(probe, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1, FileOptions.DeleteOnClose)) { }
                    settings.OutputDirectory = path;
                }
                catch (Exception e) when (e is IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException)
                { return Err(400, "No se puede guardar en esa carpeta. Elige otra ubicación con permiso de escritura."); }
            }
            if (J.B(b["completed"])) settings.SetupCompleted = true;
            _store.Settings = settings;
            return Json(new JsonObject { ["ok"] = true, ["output_dir"] = _store.OutputRoot, ["setup_completed"] = settings.SetupCompleted });
        });
    }
}
