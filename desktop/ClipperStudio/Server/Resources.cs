using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using ClipperStudio.Engine;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;

namespace ClipperStudio.Server;

public partial class Api
{
    const long ResourceLimit = 100 * 1024 * 1024;
    static readonly Dictionary<string,(string Kind,string Mime)> ResourceTypes = new()
    {
        [".png"]=("image","image/png"), [".jpg"]=("image","image/jpeg"), [".jpeg"]=("image","image/jpeg"),
        [".webp"]=("image","image/webp"), [".gif"]=("image","image/gif"), [".wav"]=("audio","audio/wav"),
        [".mp3"]=("audio","audio/mpeg"), [".m4a"]=("audio","audio/mp4"), [".ogg"]=("audio","audio/ogg"),
        [".flac"]=("audio","audio/flac"), [".pdf"]=("document","application/pdf"), [".txt"]=("document","text/plain"),
        [".md"]=("document","text/plain"), [".json"]=("document","application/json"),
    };
    void MapResources(WebApplication app)
    {
        bool ValidProject(string project) => HasProject(project) && Regex.IsMatch(project,"^[A-Za-z0-9_-]+$");
        app.MapGet("/api/projects/{project}/resources", (string project) =>
            ValidProject(project) ? Json(Arr(_store.List("resources",project))) : Err(404,"No existe el proyecto."));
        app.MapPost("/api/projects/{project}/resources", async (string project,HttpRequest req) =>
        {
            if(!ValidProject(project))return Err(404,"No existe el proyecto.");
            var form=await req.ReadFormAsync();
            var file=form.Files.GetFile("file");
            if(file==null || file.Length==0)return Err(400,"El archivo está vacío.");
            if(file.Length>ResourceLimit)return Err(400,"El archivo supera 100 MB.");
            var name=Regex.Replace(file.FileName.Replace('\\','/').Split('/').Last(),"[\\x00-\\x1f\\x7f]","");
            if(name.Length>180)name=name[..180];
            var extension=Path.GetExtension(name).ToLowerInvariant();
            if(!ResourceTypes.TryGetValue(extension,out var type))return Err(400,"Usa una imagen, audio, PDF, TXT, Markdown o JSON.");
            var description=form["description"].ToString().Trim();
            if(description.Length>600)return Err(400,"La descripción admite hasta 600 caracteres.");
            var id="res_"+Guid.NewGuid().ToString("N");
            var path=Path.Combine(Paths.Dir("projects",project,"resources"),id+extension);
            var record=new JsonObject{["id"]=id,["project_id"]=project,["name"]=name,["extension"]=extension,["kind"]=type.Kind,["size"]=file.Length,["description"]=description,["created_at"]=Store.Now()};
            try
            {
                await using(var output=File.Create(path))await file.CopyToAsync(output);
                _store.Add("resources",record);
            }
            catch{File.Delete(path);throw;}
            return Json(record);
        });
        app.MapGet("/api/projects/{project}/resources/{id}/file", (string project,string id,bool? download,HttpResponse response) =>
        {
            if(!ValidProject(project))return Err(404,"No existe el proyecto.");
            var record=_store.Get("resources",id);
            if(record==null || J.S(record["project_id"])!=project)return Err(404,"No existe este recurso en el proyecto.");
            var extension=J.S(record["extension"]);
            if(!ResourceTypes.TryGetValue(extension,out var type))return Err(404,"Tipo de recurso no válido.");
            var path=Path.Combine(Paths.Data,"projects",project,"resources",J.S(record["id"])+extension);
            if(!File.Exists(path))return Err(404,"No se encuentra el archivo del recurso.");
            response.Headers["X-Content-Type-Options"]="nosniff";
            return Results.File(path,type.Mime,download==true || type.Kind=="document" ? J.S(record["name"]) : null,enableRangeProcessing:true);
        });
    }
}
