using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using ClipperStudio.Engine;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;

namespace ClipperStudio.Server;

public partial class Api
{
    readonly SemaphoreSlim _mutations = new(1,1);
    readonly string _csrf = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
    readonly string _session = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
    const string SecurityPolicy = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'";
    void Secure(WebApplication app)
    {
        app.Use(async (context,next) =>
        {
            var req=context.Request;
            string authority=req.Host.Value??"";
            bool local=req.Host.Host=="127.0.0.1" && req.Host.Port==context.Connection.LocalPort;
            string origin=req.Headers.Origin.ToString();
            if(!local || origin!="" && (!Uri.TryCreate(origin,UriKind.Absolute,out var source) || source.Authority!=authority || source.Scheme!=req.Scheme))
            {context.Response.StatusCode=403;return;}
            var cookieName="kairos_session_"+context.Connection.LocalPort;
            bool Equal(string? value,string expected)=>value!=null && CryptographicOperations.FixedTimeEquals(System.Text.Encoding.UTF8.GetBytes(value),System.Text.Encoding.UTF8.GetBytes(expected));
            if(req.Path.StartsWithSegments("/api"))
            {
                if(!Equal(req.Cookies[cookieName],_session)){context.Response.StatusCode=401;return;}
                if(req.Method is not ("GET" or "HEAD" or "OPTIONS") && !Equal(req.Headers["X-Kairos-CSRF"].ToString(),_csrf)){context.Response.StatusCode=403;return;}
                context.Response.Headers.CacheControl="no-store";
            }
            context.Response.Headers["X-Content-Type-Options"]="nosniff";
            context.Response.Headers["X-Frame-Options"]="DENY";
            context.Response.Headers["Referrer-Policy"]="no-referrer";
            context.Response.Headers["Content-Security-Policy"]=SecurityPolicy;
            if(req.Path=="/")
            {
                context.Response.Headers.CacheControl="no-store";
                context.Response.Cookies.Append(cookieName,_session,new CookieOptions{HttpOnly=true,SameSite=SameSiteMode.Strict,Secure=false,Path="/"});
            }
            bool mutation=req.Method is not ("GET" or "HEAD" or "OPTIONS");
            if(mutation)await _mutations.WaitAsync();
            try{await next(context);}finally{if(mutation)_mutations.Release();}
        });
    }
    string Redact(string value)
    {
        foreach(var pid in new[]{"anthropic","openai","gemini","openrouter","mistral","deepseek","groq","ollama","custom"})
        {
            var key=_ai.Conf(pid).Key;
            if(key is {Length:>6}) value=value.Replace(key,"[REDACTED]",StringComparison.Ordinal);
        }
        return Regex.Replace(value,@"(?:sk-(?:ant-)?|gsk_|AIza)[A-Za-z0-9_\-]{16,}","[REDACTED]");
    }
}
