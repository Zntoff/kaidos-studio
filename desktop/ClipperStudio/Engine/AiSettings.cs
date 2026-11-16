// Each person's own connection to an AI provider: which provider, their API key for it (encrypted for this
// Windows user), the models used per tier, the prices they pay, a budget, and a ledger of calls.
// Same JSON shapes as clipper/ai_settings.py, so one Settings screen serves both apps. The provider catalog
// is config/providers.json, shared with the Docker app.
// No provider returns the prepaid balance through the API, so "remaining" is the budget the person typed in
// minus what this app has spent since then.
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace ClipperStudio.Engine;

public class KeyRejectedException(string message) : Exception(message);

/// <summary>A catalog entry merged with what the person configured.</summary>
public record ProviderConf(string Id, string Name, string Kind, string BaseUrl, string Dialect, string MaxTokensField,
    Dictionary<string, string> Models, Dictionary<string, double[]> Prices, string? Key, string? KeySource,
    bool NeedsKey, bool EditableUrl, string? KeyUrl, string? Note, string? KeyPrefix, Dictionary<string, string> TierNames);

public class AiSettings
{
    static readonly object Lock = new();
    static readonly HttpClient Http = new(new HttpClientHandler { AllowAutoRedirect = false }) { Timeout = TimeSpan.FromSeconds(30) };
    public static readonly string[] Tiers = ["fast", "standard", "superior"];
    static readonly Dictionary<string, string> GenericTierNames = new() { ["fast"] = "Rápido", ["standard"] = "Estándar", ["superior"] = "Superior" };
    static readonly Dictionary<string, (double inp, double outp)> AnthropicFamilies = new() { ["fast"] = (0.10, 0.50), ["standard"] = (2, 10), ["superior"] = (4, 20) };
    static JsonArray? _catalog;
    readonly string _file = Path.Combine(Paths.Dir(), "settings.ai.json"), _ledger = Path.Combine(Paths.Dir(), "usage.jsonl");

    public static JsonArray Catalog
    {
        get
        {
            if (_catalog != null) return _catalog;
            var path = Path.Combine(Paths.App, "config", "providers.json");
            return _catalog = JsonNode.Parse(File.ReadAllText(path))!["providers"]!.AsArray();
        }
    }

    public static JsonNode? Meta(string pid) => Catalog.FirstOrDefault(p => J.S(p!["id"]) == pid);

    JsonObject Load()
    {
        try { return JsonNode.Parse(File.ReadAllText(_file)) as JsonObject ?? []; } catch { return []; }
    }

    void Save(Action<JsonObject> change)
    {
        lock (Lock)
        {
            var d = Load();
            change(d);
            File.WriteAllText(_file + ".tmp", d.ToJsonString(J.Pretty));
            File.Move(_file + ".tmp", _file, true);
        }
    }

    static JsonObject ProviderEntry(JsonObject d, string pid)
    {
        if (d["providers"] is not JsonObject all) d["providers"] = all = [];
        if (all[pid] is not JsonObject entry) all[pid] = entry = [];
        return entry;
    }

    static string? Decrypt(string enc)
    {
        if (enc == "") return null;
        try { return Encoding.UTF8.GetString(ProtectedData.Unprotect(Convert.FromBase64String(enc), null, DataProtectionScope.CurrentUser)); }
        catch (Exception e) when (e is CryptographicException or FormatException) { return null; }   // the file came from another Windows user
    }

    static string Encrypt(string key) => Convert.ToBase64String(ProtectedData.Protect(Encoding.UTF8.GetBytes(key), null, DataProtectionScope.CurrentUser));

    // ---------- provider configuration ----------
    public string ActiveId
    {
        get
        {
            var pid = J.S(Load()["provider"]);
            if (pid == "") pid = Environment.GetEnvironmentVariable("CLIPPER_AI_PROVIDER") ?? "anthropic";
            return Meta(pid) != null ? pid : "anthropic";
        }
    }

    (string? key, string? source) KeyFor(JsonObject d, string pid)
    {
        var enc = J.S(d["providers"]?[pid]?["api_key_dpapi"]);
        if (enc == "" && pid == "anthropic") enc = J.S(d["api_key_dpapi"]);   // where the key lived before multi-provider support
        if (Decrypt(enc) is { } k) return (k, "panel");
        var env = J.S(Meta(pid)?["env"]);
        return env != "" && Environment.GetEnvironmentVariable(env) is { Length: > 0 } e ? (e, "env") : (null, null);
    }

    public ProviderConf Conf(string? pid = null)
    {
        pid ??= ActiveId;
        var m = Meta(pid) ?? Meta("anthropic")!;
        pid = J.S(m["id"]);
        var d = Load();
        var stored = d["providers"]?[pid] as JsonObject;
        var models = Tiers.ToDictionary(t => t, t => J.S(m["models"]?[t]));
        if (pid == "anthropic")
            foreach (var t in Tiers)
                if (Environment.GetEnvironmentVariable($"CLIPPER_MODEL_{t.ToUpperInvariant()}") is { Length: > 0 } env) models[t] = env;
        foreach (var t in Tiers)
            if (J.S(stored?["models"]?[t]) is { Length: > 0 } v) models[t] = v;
        var prices = new Dictionary<string, double[]>();
        foreach (var t in Tiers)
        {
            var p = stored?["prices"]?[t] as JsonArray ?? m["prices"]?[t] as JsonArray;
            if (p is { Count: 2 }) prices[t] = [J.D(p[0]), J.D(p[1])];
        }
        var (key, source) = KeyFor(d, pid);
        var url = J.S(stored?["base_url"]) is { Length: > 0 } u ? u : J.S(m["base_url"]);
        var names = m["tier_names"] is JsonObject tn ? Tiers.ToDictionary(t => t, t => J.S(tn[t])) : new Dictionary<string, string>(GenericTierNames);
        return new ProviderConf(pid, J.S(m["name"]), J.S(m["kind"], "openai"), url.TrimEnd('/'), J.S(m["dialect"]), J.S(m["max_tokens_field"], "max_tokens"),
            models, prices, key, source, J.B(m["needs_key"]), J.B(m["editable_url"]), m["key_url"] == null ? null : J.S(m["key_url"]),
            m["note"] == null ? null : J.S(m["note"]), m["key_prefix"] == null ? null : J.S(m["key_prefix"]), names);
    }

    /// <summary>Why this provider cannot run a job yet, in words for the person; null when it can.</summary>
    public static string? CredentialTransportError(string url,string? key)
    {
        if(string.IsNullOrEmpty(key))return null;
        if(Uri.TryCreate(url,UriKind.Absolute,out var uri) && (uri.Scheme=="https" || uri.Scheme=="http" && uri.Host is "localhost" or "127.0.0.1" or "::1" or "[::1]"))return null;
        return "Use HTTPS to protect your API key. HTTP is allowed only for local loopback servers.";
    }
    public static string? Missing(ProviderConf c)
    {
        if (c.NeedsKey && c.Key == null) return $"Falta la API key de {c.Name}. Añádela en Ajustes.";
        if (c.BaseUrl == "") return $"Falta la dirección del servidor de {c.Name}. Complétala en Ajustes.";
        if(CredentialTransportError(c.BaseUrl,c.Key) is {} transportError)return transportError;
        var empty = Tiers.Where(t => c.Models[t] == "").Select(t => GenericTierNames[t].ToLowerInvariant()).ToList();
        return empty.Count > 0 ? $"Elige los modelos de {c.Name} ({string.Join(", ", empty)}) en Ajustes." : null;
    }

    public string? MissingActive => Missing(Conf());

    /// <summary>The active provider's key (panel or environment).</summary>
    public string? Key => Conf().Key;

    public static string Hint(string? key) => key == null ? "" : key.Length >= 24 ? $"{key[..7]}…{key[^4..]}" : key.Length >= 12 ? $"{key[..3]}…{key[^2..]}" : "••••••";
    static string NowIso() => DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");

    public static bool ValidFormat(string key, string pid = "anthropic")
    {
        if (key.Length < 8 || key.Any(c => c >= 128 || char.IsWhiteSpace(c) || char.IsControl(c))) return false;
        var prefix = J.S(Meta(pid)?["key_prefix"]);
        return prefix == "" || key.StartsWith(prefix) && key.Length >= 30;
    }

    public JsonObject State()
    {
        var d = Load();
        var active = Conf();
        var providers = new JsonArray();
        foreach (var p in Catalog)
        {
            var c = Conf(J.S(p!["id"]));
            providers.Add(new JsonObject
            {
                ["id"] = c.Id, ["name"] = c.Name, ["kind"] = c.Kind, ["needs_key"] = c.NeedsKey, ["key_url"] = c.KeyUrl, ["note"] = c.Note,
                ["editable_url"] = c.EditableUrl, ["base_url"] = c.BaseUrl,
                ["models"] = new JsonObject(c.Models.Select(kv => KeyValuePair.Create(kv.Key, (JsonNode?)kv.Value))),
                ["prices"] = new JsonObject(c.Prices.Select(kv => KeyValuePair.Create(kv.Key, (JsonNode?)new JsonArray(kv.Value[0], kv.Value[1])))),
                ["key_set"] = c.Key != null, ["key_hint"] = Hint(c.Key), ["source"] = c.KeySource,
                ["tier_names"] = new JsonObject(c.TierNames.Select(kv => KeyValuePair.Create(kv.Key, (JsonNode?)kv.Value))),
                ["missing"] = Missing(c),
            });
        }
        var missing = Missing(active);
        return new JsonObject
        {
            ["provider"] = active.Id, ["provider_name"] = active.Name, ["providers"] = providers,
            ["key_set"] = active.Key != null, ["key_hint"] = Hint(active.Key), ["source"] = active.KeySource,
            ["ready"] = missing == null, ["missing"] = missing,
            ["limits"] = active.Id == "anthropic" && d["limits"] != null ? J.Clone(d["limits"]!) : null, ["llm"] = "anthropic",
            ["budget"] = d["budget"] is JsonObject b ? J.Clone(b) : new JsonObject { ["usd"] = null, ["since"] = null },
        };
    }

    /// <summary>Verify and store a key. Returns a warning (or null) and, for OpenAI-compatible providers, their models.</summary>
    public async Task<(string? warning, List<string>? models)> SetKeyAsync(string key, string? pid = null)
    {
        pid ??= ActiveId;
        var name = J.S(Meta(pid)?["name"], pid);
        key = key.Trim();
        if (!ValidFormat(key, pid))
            throw new KeyRejectedException(pid == "anthropic"
                ? "Esa no parece una API key de Anthropic: empieza por «sk-ant-» y es larga. Cópiala completa desde console.anthropic.com."
                : $"Esa no parece una API key de {name}: cópiala completa, sin espacios.");
        var (warning, limits, models) = await VerifyAsync(pid, key);
        var enc = Encrypt(key);
        Save(d =>
        {
            ProviderEntry(d, pid)["api_key_dpapi"] = enc;
            if (pid == "anthropic") { d["api_key_dpapi"] = enc; d["limits"] = limits; }   // keep the legacy field for older builds
        });
        return (warning, models);
    }

    public async Task<(string? warning, List<string>? models)> TestAsync(string? pid = null)
    {
        var c = Conf(pid);
        if (c.NeedsKey && c.Key == null) throw new KeyRejectedException("Todavía no hay una API key.");
        var (warning, limits, models) = await VerifyAsync(c.Id, c.Key);
        if (c.Id == "anthropic" && limits != null) Save(d => d["limits"] = limits);
        return (warning, models);
    }

    public void RemoveKey(string? pid = null)
    {
        pid ??= ActiveId;
        Save(d =>
        {
            ProviderEntry(d, pid).Remove("api_key_dpapi");
            if (pid == "anthropic") { d.Remove("api_key_dpapi"); d["limits"] = null; }
        });
    }

    public void SetProvider(string pid, string? baseUrl, JsonObject? models, JsonObject? prices, bool activate)
    {
        var m = Meta(pid) ?? throw new KeyRejectedException("Proveedor desconocido.");
        Save(d =>
        {
            var e = ProviderEntry(d, pid);
            if (baseUrl != null && J.B(m["editable_url"])) e["base_url"] = baseUrl.Trim().TrimEnd('/');
            if (models != null) e["models"] = new JsonObject(Tiers.Select(t => KeyValuePair.Create(t, (JsonNode?)J.S(models[t]).Trim())));
            if (prices != null)
                e["prices"] = new JsonObject(Tiers.Where(t => prices[t] is JsonArray { Count: 2 })
                    .Select(t => KeyValuePair.Create(t, (JsonNode?)new JsonArray(J.D(prices[t]![0]), J.D(prices[t]![1])))));
            if (activate) d["provider"] = pid;
        });
    }

    public void SetBudget(double? usd) => Save(d => d["budget"] = new JsonObject { ["usd"] = usd, ["since"] = NowIso() });

    /// <summary>Anthropic: a one-token call (also returns rate limits). OpenAI-compatible: list the models, which costs nothing.</summary>
    async Task<(string? warning, JsonNode? limits, List<string>? models)> VerifyAsync(string pid, string? key)
    {
        var c = Conf(pid);
        if (c.Kind != "anthropic")
        {
            var list = await ListModelsAsync(c, key);
            return (list.Count == 0 ? $"{c.Name} respondió, pero no devolvió modelos." : null, null, list);
        }
        var (w, l) = await VerifyAnthropicAsync(key!, c.Models["fast"] is { Length: > 0 } f ? f : "claude-haiku-5-5");
        return (w, l, null);
    }

    public Task<List<string>> ListModelsAsync(string pid) => ListModelsAsync(Conf(pid), Conf(pid).Key);

    static async Task<List<string>> ListModelsAsync(ProviderConf c, string? key)
    {
        if (c.BaseUrl == "") throw new KeyRejectedException("Falta la dirección del servidor.");
        if(CredentialTransportError(c.BaseUrl,key) is {} transportError)throw new KeyRejectedException(transportError);
        var baseUrl = c.BaseUrl.TrimEnd('/');
        if (c.Kind == "anthropic" && !baseUrl.EndsWith("/v1")) baseUrl += "/v1";
        using var req = new HttpRequestMessage(HttpMethod.Get, baseUrl + "/models");
        if (c.Kind == "anthropic") {
            req.Headers.Add("x-api-key", key ?? "");
            req.Headers.Add("anthropic-version", "2023-06-01");
        } else if (!string.IsNullOrEmpty(key)) req.Headers.Add("Authorization", "Bearer " + key);
        HttpResponseMessage res;
        try { res = await Http.SendAsync(req); }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException) { throw new KeyRejectedException($"No se pudo conectar con {c.Name} en {c.BaseUrl}. Revisa la dirección y tu conexión."); }
        var body = await res.Content.ReadAsStringAsync();
        if ((int)res.StatusCode is 401 or 403) throw new KeyRejectedException($"{c.Name} rechazó esta API key. Revisa que esté completa y que no esté revocada.");
        if (!res.IsSuccessStatusCode) throw new KeyRejectedException($"{c.Name} respondió {(int)res.StatusCode}: provider request failed");
        JsonNode? doc;
        try { doc = JsonNode.Parse(body); } catch (System.Text.Json.JsonException) { throw new KeyRejectedException($"{c.Name} no respondió con la API de OpenAI en {c.BaseUrl}."); }
        var items = doc?["data"] as JsonArray ?? doc?["models"] as JsonArray ?? [];
        var ids = items.Select(i => J.S(i?["id"]) is { Length: > 0 } id ? id : J.S(i?["name"])).Where(s => s != "")
            .Select(s => c.Dialect == "gemini" && s.StartsWith("models/") ? s[7..] : s);
        return ids.Distinct().OrderBy(s => s, StringComparer.Ordinal).ToList();
    }

    async Task<(string? warning, JsonNode? limits)> VerifyAnthropicAsync(string key, string model)
    {
        using var req = new HttpRequestMessage(HttpMethod.Post, "https://api.anthropic.com/v1/messages")
        {
            Content = new StringContent(new JsonObject
            {
                ["model"] = model, ["max_tokens"] = 1, ["messages"] = new JsonArray(new JsonObject { ["role"] = "user", ["content"] = "ping" }),
            }.ToJsonString(), Encoding.UTF8, "application/json"),
        };
        req.Headers.Add("x-api-key", key);
        req.Headers.Add("anthropic-version", "2023-06-01");
        HttpResponseMessage res;
        try { res = await Http.SendAsync(req); }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException) { throw new KeyRejectedException("No se pudo conectar con Anthropic. Revisa tu conexión a internet."); }
        var body = await res.Content.ReadAsStringAsync();
        if (!res.IsSuccessStatusCode)
        {
            switch ((int)res.StatusCode)
            {
                case 401: throw new KeyRejectedException("Anthropic rechazó esta API key. Revisa que esté completa y que no esté revocada.");
                case 403: throw new KeyRejectedException("Esta API key no tiene permiso para usar los modelos. Revisa su espacio de trabajo en la consola.");
                case 429: return ("La key es válida, pero ahora mismo está en el límite de peticiones. Inténtalo en un minuto.", null);
                case 400 when body.Contains("credit balance", StringComparison.OrdinalIgnoreCase):
                    return ("La key es válida, pero la cuenta no tiene crédito. Añade saldo en console.anthropic.com.", null);
                default: throw new KeyRejectedException($"Anthropic respondió {(int)res.StatusCode}: provider request failed");
            }
        }
        var msg = JsonNode.Parse(body)!;
        AddUsage("prueba", J.S(msg["model"], model), (long)J.D(msg["usage"]?["input_tokens"]), (long)J.D(msg["usage"]?["output_tokens"]), "anthropic");
        var limits = new JsonObject { ["checked_at"] = NowIso() };
        foreach (var name in new[] { "requests", "tokens", "input-tokens", "output-tokens" })
            if (res.Headers.TryGetValues($"anthropic-ratelimit-{name}-limit", out var lim) && res.Headers.TryGetValues($"anthropic-ratelimit-{name}-remaining", out var rem))
                limits[name.Replace('-', '_')] = new JsonObject
                {
                    ["limit"] = long.Parse(lim.First()), ["remaining"] = long.Parse(rem.First()),
                    ["reset"] = res.Headers.TryGetValues($"anthropic-ratelimit-{name}-reset", out var rs) ? rs.First() : null,
                };
        return (null, limits.Count > 1 ? limits : null);
    }

    // ---------- ledger ----------
    public void AddUsage(string agent, string model, long input, long output, string? provider = null)
    {
        var line = new JsonObject { ["ts"] = NowIso(), ["provider"] = provider ?? ActiveId, ["agent"] = agent, ["model"] = model, ["input"] = input, ["output"] = output }.ToJsonString();
        lock (Lock) File.AppendAllText(_ledger, line + "\n");
    }

    /// <summary>model id → price, from every provider's configured models; Anthropic models outside the tiers by family.</summary>
    Dictionary<string, double[]> PriceTable()
    {
        var table = new Dictionary<string, double[]>();
        foreach (var p in Catalog)
        {
            var c = Conf(J.S(p!["id"]));
            foreach (var t in Tiers)
                if (c.Models[t] != "" && c.Prices.TryGetValue(t, out var price)) table.TryAdd(c.Id + "\n" + c.Models[t], price);
        }
        return table;
    }

    static double[]? PriceFor(Dictionary<string, double[]> table, string model, string provider = "anthropic")
    {
        if (table.TryGetValue(provider + "\n" + model, out var p)) return p;
        if (provider != "anthropic") return null;
        var m = model.ToLowerInvariant();
        if (!m.Contains("claude") && m != "") return null;
        var (i, o) = AnthropicFamilies[m.Contains("haiku") ? "fast" : m.Contains("opus") ? "superior" : "standard"];
        return [i, o];
    }

    static double Cost(Dictionary<string, double[]> table, JsonNode r) =>
        PriceFor(table, J.S(r["model"]), J.S(r["provider"], "anthropic")) is { } p ? J.D(r["input"]) * p[0] / 1e6 + J.D(r["output"]) * p[1] / 1e6 : 0;

    List<JsonNode> Read(string? since)
    {
        var rows = new List<JsonNode>();
        string[] lines;
        lock (Lock) { try { lines = File.ReadAllLines(_ledger); } catch (IOException) { return rows; } }
        foreach (var l in lines)
        {
            try { if (JsonNode.Parse(l) is { } r && (since == null || string.CompareOrdinal(J.S(r["ts"]), since) >= 0)) rows.Add(r); } catch (System.Text.Json.JsonException) { }
        }
        return rows;
    }

    public JsonObject Summarize(int days)
    {
        var d = Load();
        var table = PriceTable();
        var today = DateTime.UtcNow.Date;
        var first = today.AddDays(-(days - 1));
        var rows = Read(first.ToString("yyyy-MM-dd"));
        var byDay = Enumerable.Range(0, days).Select(i => first.AddDays(i).ToString("yyyy-MM-dd")).ToDictionary(k => k, k => (cost: 0.0, calls: 0));
        var byModel = new Dictionary<(string provider, string model), (string provider, long calls, long input, long output, double cost)>();
        long calls = 0, tin = 0, tout = 0, unpriced = 0;
        double total = 0;
        foreach (var r in rows)
        {
            double c = Cost(table, r);
            long i = (long)J.D(r["input"]), o = (long)J.D(r["output"]);
            var model = J.S(r["model"], "?");
            var provider = J.S(r["provider"], "anthropic");
            var key = (provider, model);
            if (PriceFor(table, model, provider) == null) unpriced++;
            var m = byModel.GetValueOrDefault(key);
            byModel[key] = (provider, m.calls + 1, m.input + i, m.output + o, m.cost + c);
            calls++; tin += i; tout += o; total += c;
            var day = J.S(r["ts"])[..Math.Min(10, J.S(r["ts"]).Length)];
            if (byDay.TryGetValue(day, out var bd)) byDay[day] = (bd.cost + c, bd.calls + 1);
        }
        var budget = d["budget"] as JsonObject;
        double? usd = budget?["usd"] is JsonValue ? J.D(budget["usd"]) : null;
        double? spent = usd == null ? null : Read(J.S(budget!["since"])).Sum(r => Cost(table, r));
        var active = Conf();
        return new JsonObject
        {
            ["days"] = days,
            ["totals"] = new JsonObject { ["calls"] = calls, ["input"] = tin, ["output"] = tout, ["cost"] = total, ["unpriced_calls"] = unpriced },
            ["by_model"] = new JsonArray(byModel.OrderByDescending(kv => kv.Value.cost).Select(kv => (JsonNode)new JsonObject
            {
                ["model"] = kv.Key.model, ["provider"] = kv.Value.provider, ["calls"] = kv.Value.calls, ["input"] = kv.Value.input, ["output"] = kv.Value.output,
                ["cost"] = kv.Value.cost, ["priced"] = PriceFor(table, kv.Key.model, kv.Key.provider) != null,
            }).ToArray()),
            ["by_day"] = new JsonArray(byDay.Select(kv => (JsonNode)new JsonObject { ["day"] = kv.Key, ["cost"] = kv.Value.cost, ["calls"] = kv.Value.calls }).ToArray()),
            ["budget"] = new JsonObject { ["usd"] = usd, ["since"] = budget?["since"] is JsonValue ? J.S(budget["since"]) : null, ["spent"] = spent, ["remaining"] = usd - spent },
            ["provider"] = new JsonObject { ["id"] = active.Id, ["name"] = active.Name },
            ["prices"] = new JsonObject(Tiers.Select(t => KeyValuePair.Create(t, (JsonNode?)new JsonObject
            {
                ["name"] = active.TierNames[t], ["model"] = active.Models[t],
                ["input"] = active.Prices.TryGetValue(t, out var p) ? p[0] : null, ["output"] = active.Prices.TryGetValue(t, out var q) ? q[1] : null,
            }))),
            ["limits"] = d["limits"] == null ? null : J.Clone(d["limits"]!),
        };
    }
}
