using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using ClipperStudio.Engine;
using ClipperStudio.Server;
using Microsoft.Web.WebView2.Core;

namespace ClipperStudio;

/// <summary>The window: a WebView2 showing the interface, served by the engine's local API.</summary>
public partial class MainWindow : Window
{
    readonly Api _api = new();

    public MainWindow()
    {
        InitializeComponent();
        Status.Text=UiText.Get("Preparando FFmpeg y la GPU\u2026");
        var area = SystemParameters.WorkArea;
        Width = Math.Min(Width, Math.Max(MinWidth, area.Width - 32));
        Height = Math.Min(Height, Math.Max(MinHeight, area.Height - 32));
        _api.SelectOutputFolder = async language => await Dispatcher.InvokeAsync(() =>
        {
            var dialog = new Microsoft.Win32.OpenFolderDialog { Title = UiText.Get("Dónde guardar los videos generados",language) };
            return dialog.ShowDialog(this) == true ? dialog.FolderName : null;
        });
        SourceInitialized += (_, _) => DarkTitleBar();
        Loaded += async (_, _) => await StartAsync();
        Closed += async (_, _) => await _api.StopAsync();
    }

    async Task StartAsync()
    {
        try
        {
            await _api.StartAsync();
            // The browser profile lives with the app's data, not next to the executable.
            var env = await CoreWebView2Environment.CreateAsync(null, Paths.Dir("webview"),
                new CoreWebView2EnvironmentOptions("--autoplay-policy=no-user-gesture-required"));
            await Web.EnsureCoreWebView2Async(env);
            var s = Web.CoreWebView2.Settings;
            s.AreDefaultContextMenusEnabled = false;
            s.IsStatusBarEnabled = false;
            s.IsZoomControlEnabled = false;
            s.AreBrowserAcceleratorKeysEnabled = false;      // F5, Ctrl+P and friends belong to a browser, not to an editor
            s.IsSwipeNavigationEnabled = false;
#if DEBUG
            s.AreDevToolsEnabled = true;
            s.AreBrowserAcceleratorKeysEnabled = true;
#else
            s.AreDevToolsEnabled = false;
#endif
            Web.CoreWebView2.NewWindowRequested += (_, e) => e.Handled = true;
            Web.CoreWebView2.NavigationStarting += (_, e) => { if (!Uri.TryCreate(e.Uri,UriKind.Absolute,out var target) || target.GetLeftPart(UriPartial.Authority) != new Uri(_api.Url).GetLeftPart(UriPartial.Authority)) e.Cancel = true; };
            Web.CoreWebView2.DocumentTitleChanged += (_, _) => Title = Web.CoreWebView2.DocumentTitle is { Length: > 0 } t ? t : "Kairos Studio";
            Web.NavigationCompleted += (_, _) => Splash.Visibility = Visibility.Collapsed;
            Web.CoreWebView2.Navigate(_api.Url);
        }
        catch (Exception e)
        {
            Status.Text = UiText.Get("No se pudo iniciar Kairos Studio.")+"\n\n" + e.Message +
                          (e is WebView2RuntimeNotFoundException ? "\n\n"+UiText.Get("Instala «Microsoft Edge WebView2 Runtime» y vuelve a abrir la app.") : "");
        }
    }

    // Windows 11 draws a light title bar unless the window asks for the dark one.
    [DllImport("dwmapi.dll")]
    static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

    void DarkTitleBar()
    {
        var hwnd = new WindowInteropHelper(this).Handle;
        int on = 1, color = 0x000E0B0A;                                         // COLORREF is 0x00BBGGRR: #0A0B0E
        DwmSetWindowAttribute(hwnd, 20 /* DWMWA_USE_IMMERSIVE_DARK_MODE */, ref on, sizeof(int));
        DwmSetWindowAttribute(hwnd, 35 /* DWMWA_CAPTION_COLOR */, ref color, sizeof(int));
    }
}
