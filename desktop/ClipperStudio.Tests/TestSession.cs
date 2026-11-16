using System.Text.RegularExpressions;

static class TestSession
{
    public static async Task Open(HttpClient client)
    {
        var html=await client.GetStringAsync("/");
        var match=Regex.Match(html,"name=\"kairos-csrf\" content=\"([a-fA-F0-9]+)\"");
        if(!match.Success)throw new Exception("Session bootstrap failed");
        client.DefaultRequestHeaders.Remove("X-Kairos-CSRF");
        client.DefaultRequestHeaders.Add("X-Kairos-CSRF",match.Groups[1].Value);
    }
}
