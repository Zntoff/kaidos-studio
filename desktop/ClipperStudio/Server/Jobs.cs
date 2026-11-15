using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using ClipperStudio.Ai;
using ClipperStudio.Engine;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;

namespace ClipperStudio.Server;

public partial class Api
{
    readonly object _jobLock = new();
    static readonly string[] ModelTiers = ["fast", "standard", "superior"];
    static readonly Regex LanguageCode = new("^[a-z]{2,3}(-[A-Za-z]{2,4})?$");

    bool JobActive(string id) => _runs.All.Any(r => r.JobId == id && r.Status is "queued" or "running");

    static string? CheckOptions(JsonNode b)
    {
        foreach (var field in new[] { "model", "analysis_model" })
            if (b[field] != null && !ModelTiers.Contains(J.S(b[field]))) return "Modelo no válido.";
        if (b["layout"] != null && !Pipeline.LayoutChoices.Contains(J.S(b["layout"]))) return "Encuadre no válido.";
        if (b["caption_style"] != null && !Pipeline.CaptionChoices.Contains(J.S(b["caption_style"]))) return "Estilo de subtítulos no válido.";
        if (b["languages"] != null && (b["languages"] is not JsonArray || J.Items(b["languages"]).Any(l => !LanguageCode.IsMatch(J.S(l)))))
            return "Los idiomas deben ser una lista de códigos válidos.";
        return null;
    }

    string LaunchJob(string id, string label, JsonObject options)
    {
        var provider = _ai.Conf();
        _store.Update("jobs", id, ("status", "running"), ("options", options), ("summary", null));
        return _runs.Start(label, log =>
        {
            var job = _store.Get("jobs", id)!;
            if (job["analysis"] == null) _pipeline.AnalyzeAsync(id, log, provider).GetAwaiter().GetResult();
            else
            {
                var picks = J.Items(options["selection"]).Select(n => J.S(n)).ToList();
                if (picks.Count == 0) { _store.Update("jobs", id, ("status", "awaiting_selection")); return; }
                _pipeline.GenerateAsync(id, picks, J.S(options["model"], "standard"), J.S(options["layout"], "auto"),
                    J.S(options["caption_style"], "auto"), J.Items(options["languages"]).Select(n => J.S(n)).ToList(), log, provider).GetAwaiter().GetResult();
            }
        }, id);
    }

    void MapJobs(WebApplication app)
    {
        app.MapPost("/api/clips/{id}/creative-version", async (string id, HttpRequest req) =>
        {
            var b = req.ContentLength is > 0 ? await JsonNode.ParseAsync(req.Body) ?? new JsonObject() : new JsonObject();
            lock (_jobLock)
            {
                if (_store.Get("clips", id) is not { } clip) return Err(404, "No existe el clip.");
                var jobId = J.S(clip["job_id"]);
                if (_store.Get("jobs", jobId) is not { } job || job["analysis"] == null) return Err(400, "Este clip no tiene un análisis guardado. Procesa primero el video.");
                if (_ai.MissingActive is { } missing) return Err(400, missing);
                if (JobActive(jobId)) return Err(409, "Este trabajo ya tiene una ejecución en curso.");
                string tier = J.S(b["model"], J.S(job["options"]?["model"], "standard"));
                if (!ModelTiers.Contains(tier)) return Err(400, "Modelo no válido.");
                string layout = J.S(b["layout"], "auto");
                if (!Pipeline.LayoutChoices.Contains(layout)) return Err(400, "Encuadre no válido.");
                var newId = "creative_" + Guid.NewGuid().ToString("N")[..10];
                var provider = _ai.Conf();
                return Json(new JsonObject { ["clip_id"] = newId, ["run_id"] = _runs.Start($"Edición creativa {id}",
                    log => _pipeline.CreativeVersionAsync(id, newId, tier, log, layout, provider).GetAwaiter().GetResult(), jobId) });
            }
        });
        app.MapGet("/api/jobs", (string? project_id) => Json(Arr(_store.List("jobs", project_id).Select(job =>
        {
            job["clip_counts"] = new JsonObject(_store.List("clips").Where(c => J.S(c["job_id"]) == J.S(job["id"]))
                .GroupBy(c => J.S(c["status"])).Select(g => new KeyValuePair<string, JsonNode?>(g.Key, JsonValue.Create(g.Count()))));
            return (JsonNode)job;
        }))));
        app.MapGet("/api/jobs/{id}", (string id) =>
        {
            if (_store.Get("jobs", id) is not { } job) return Err(404, "No existe el trabajo.");
            return Json(new JsonObject
            {
                ["steps"] = J.Clone(job["steps"]!), ["job"] = job,
                ["clips"] = Arr(_store.List("clips").Where(c => J.S(c["job_id"]) == id).Select(c => (JsonNode)Public(c))),
                ["run"] = _runs.All.FirstOrDefault(r => r.JobId == id)?.Json(true),
            });
        });
        app.MapPost("/api/jobs", async (HttpRequest req) =>
        {
            var b = await JsonNode.ParseAsync(req.Body) ?? new JsonObject();
            if (_store.Get("sources", J.S(b["source_id"])) is not { } src) return Err(404, "Fuente no registrada.");
            if (J.B(b["offline"])) return Err(400, (_ai.MissingActive ?? "Configura tu proveedor de IA en Ajustes.") + " También puedes crear un clip manual desde Biblioteca.");
            if (_ai.MissingActive is { } missing) return Err(400, missing);
            if (b["review"] != null && !J.B(b["review"])) return Err(400, "En escritorio primero se analizan los momentos y después eliges cuáles generar.");
            var options = new JsonObject { ["analysis_model"] = J.S(b["analysis_model"], "fast"), ["review"] = true,
                ["model"] = "standard", ["layout"] = "auto", ["caption_style"] = "auto", ["languages"] = new JsonArray("es", "en") };
            if (CheckOptions(options) is { } problem) return Err(400, problem);
            lock (_jobLock)
            {
                if (_store.List("jobs").Any(j => J.S(j["source_id"]) == J.S(src["id"]) && JobActive(J.S(j["id"]))))
                    return Err(409, "Esta fuente ya está en ejecución.");
                var id = _pipeline.CreateJob(J.S(src["id"]), options);
                return Json(new JsonObject { ["run_id"] = LaunchJob(id, $"Analizar {J.S(src["id"])}", options), ["job_id"] = id });
            }
        });
        app.MapGet("/api/jobs/{id}/candidates", (string id) =>
        {
            if (_store.Get("jobs", id) is not { } job) return Err(404, "No existe el trabajo.");
            if (job["analysis"] is not JsonObject analysis) return Err(409, "Este trabajo todavía no tiene el análisis terminado.");
            var src = _store.Get("sources", J.S(job["source_id"])) ?? new JsonObject();
            var transcript = File.Exists(J.S(analysis["transcript_path"])) ? JsonNode.Parse(File.ReadAllText(J.S(analysis["transcript_path"]))) : null;
            var clips = _store.List("clips").Where(c => J.S(c["job_id"]) == id).ToList();
            var candidates = J.Items(analysis["candidates"]).Select((c, i) =>
            {
                var result = (JsonObject)J.Clone(c);
                var clip = clips.FirstOrDefault(k => (int)J.D(k["idx"]) == i);
                result["duration"] = Math.Round(J.D(c["end"]) - J.D(c["start"]), 1);
                result["text"] = string.Join(' ', J.Items(transcript?["segments"]).Where(s => J.D(s["start"]) >= J.D(c["start"]) - .01 && J.D(s["end"]) <= J.D(c["end"]) + .01).Select(s => J.S(s["text"])));
                result["clip_id"] = clip == null ? null : J.S(clip["id"]);
                result["clip_status"] = clip == null ? null : J.S(clip["status"]);
                return (JsonNode)result;
            });
            src.Remove("words");
            var detected = J.S(transcript?["language"]);
            return Json(new JsonObject { ["job"] = job, ["source"] = src, ["candidates"] = Arr(candidates), ["languages"] = new JsonArray("es", "en"),
                ["spoken"] = new JsonObject { ["detected"] = detected is "" or "und" ? null : detected, ["declared"] = J.S(src["language"]) } });
        });
        app.MapPost("/api/jobs/{id}/generate", async (string id, HttpRequest req) =>
        {
            var b = await JsonNode.ParseAsync(req.Body) ?? new JsonObject();
            if (CheckOptions(b) is { } problem) return Err(400, problem);
            lock (_jobLock)
            {
                if (_store.Get("jobs", id) is not { } job) return Err(404, "No existe el trabajo.");
                if (JobActive(id)) return Err(409, "Este trabajo ya está en ejecución.");
                if (job["analysis"] is not JsonObject analysis) return Err(409, "Primero termina el análisis.");
                var known = J.Items(analysis["candidates"]).Select(c => J.S(c["id"])).ToHashSet();
                var picks = J.Items(b["candidates"]).Select(n => J.S(n)).Distinct().ToList();
                if (picks.Count == 0 || picks.Any(p => !known.Contains(p))) return Err(400, "Elige al menos un momento válido de este análisis.");
                var options = (JsonObject)J.Clone(job["options"]!);
                foreach (var k in new[] { "model", "layout", "caption_style", "languages" }) if (b[k] != null) options[k] = J.Clone(b[k]!);
                if (!J.Items(options["languages"]).Any()) options["languages"] = new JsonArray("es", "en");
                options["selection"] = new JsonArray(picks.Select(p => (JsonNode)p).ToArray());
                return Json(new JsonObject { ["run_id"] = LaunchJob(id, $"Generar {id}", options) });
            }
        });
        app.MapPost("/api/jobs/{id}/resume", (string id) =>
        {
            lock (_jobLock)
            {
                if (_store.Get("jobs", id) is not { } job) return Err(404, "No existe el trabajo.");
                if (JobActive(id)) return Err(409, "Este trabajo ya está en ejecución.");
                return Json(new JsonObject { ["run_id"] = LaunchJob(id, $"Retomar {id}", (JsonObject)J.Clone(job["options"]!)) });
            }
        });
    }
}
