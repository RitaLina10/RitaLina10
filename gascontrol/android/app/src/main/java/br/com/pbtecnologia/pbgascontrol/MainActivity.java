package br.com.pbtecnologia.pbgascontrol;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.util.Log;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.Toast;

import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.webkit.JavaScriptReplyProxy;
import androidx.webkit.WebMessageCompat;
import androidx.webkit.WebViewAssetLoader;
import androidx.webkit.WebViewClientCompat;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;

import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Casca nativa do PB Gas Control.
 *
 * A interface (HTML/JS) vem dentro do APK e é servida na origem segura
 * https://appassets.androidplatform.net — o app abre e opera offline mesmo sem servidor.
 * A API fica no servidor configurado pelo usuário (CORS + Bearer token).
 *
 * Ponte JS ⇄ nativo restrita à origem do app (addWebMessageListener): leitor de QR e
 * gravação de arquivos exportados. Navegação para qualquer outro endereço abre no navegador.
 */
public class MainActivity extends ComponentActivity {
    private static final String TAG = "PBGas";
    static final String ASSET_HOST = "appassets.androidplatform.net";
    static final String APP_ORIGIN = "https://" + ASSET_HOST;
    private static final String START_URL = APP_ORIGIN + "/";
    private static final int MAX_FILE_BYTES = 15 * 1024 * 1024;
    private static final Pattern SAFE_NAME = Pattern.compile("[^A-Za-z0-9._-]");
    private static final Set<String> ALLOWED_MIME = new HashSet<>(Arrays.asList("text/csv",
            "application/pdf", "image/png", "application/xml", "text/xml", "text/plain", "application/json"));  // Set.of exige API 30

    private WebView webView;
    private WebViewAssetLoader assetLoader;

    // Pedido de leitura em andamento (um por vez).
    @Nullable private JavaScriptReplyProxy scanReply;
    private int scanId;

    // Pedido de localização do WebView aguardando permissão do sistema.
    @Nullable private GeolocationPermissions.Callback geoCallback;
    @Nullable private String geoOrigin;

    private final ActivityResultLauncher<ScanOptions> scanLauncher =
            registerForActivityResult(new ScanContract(), result -> {
                JavaScriptReplyProxy reply = scanReply;
                scanReply = null;
                if (reply == null) return;
                String text = result.getContents();
                if (text != null && text.length() > 200) {
                    replyError(reply, scanId, "Código lido é longo demais");
                } else {
                    replyOk(reply, scanId, text);  // null = cancelado
                }
            });

    private final ActivityResultLauncher<String> locationPermission =
            registerForActivityResult(new ActivityResultContracts.RequestPermission(), granted -> {
                if (geoCallback != null) geoCallback.invoke(geoOrigin, granted, false);
                geoCallback = null;
                geoOrigin = null;
            });

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildWebView();
        setContentView(webView);
        applyInsets();

        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack();
                } else {
                    setEnabled(false);
                    getOnBackPressedDispatcher().onBackPressed();
                }
            }
        });

        if (savedInstanceState == null || webView.restoreState(savedInstanceState) == null) {
            webView.loadUrl(START_URL);
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void buildWebView() {
        webView = new WebView(this);
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);           // localStorage + IndexedDB (fila offline)
        s.setDatabaseEnabled(true);
        s.setGeolocationEnabled(true);
        s.setAllowFileAccess(false);            // nada de file:// — só assets via AssetLoader
        s.setAllowContentAccess(false);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setSupportMultipleWindows(false);     // target=_blank vira navegação e cai no navegador externo
        s.setMediaPlaybackRequiresUserGesture(true);
        // A interface é https (origem do APK); o servidor na LAN pode ser http — a interface
        // só aceita http:// para endereços de rede local (normalizeServer em app.js).
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setUserAgentString(s.getUserAgentString() + " PBGasControl/" + BuildConfigHolder.versionName(this));
        if (WebViewFeature.isFeatureSupported(WebViewFeature.SAFE_BROWSING_ENABLE)) {
            androidx.webkit.WebSettingsCompat.setSafeBrowsingEnabled(s, true);
        }
        WebView.setWebContentsDebuggingEnabled(BuildConfigHolder.isDebuggable(this));

        assetLoader = new WebViewAssetLoader.Builder()
                .setDomain(ASSET_HOST)
                .addPathHandler("/", new WebAppPathHandler())
                .build();

        webView.setWebViewClient(new AppWebViewClient());
        webView.setWebChromeClient(new AppChromeClient());
        installBridge();
    }

    private void applyInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(webView, (v, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return WindowInsetsCompat.CONSUMED;
        });
    }

    // ---------------------------------------------------------------- ponte JS ⇄ nativo

    private void installBridge() {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            Log.w(TAG, "WebView sem WEB_MESSAGE_LISTENER; leitor nativo e exportação indisponíveis");
            Toast.makeText(this, "Atualize o \"Android System WebView\" pela Play Store", Toast.LENGTH_LONG).show();
            return;
        }
        WebViewCompat.addWebMessageListener(webView, "PBGasAndroid", Collections.singleton(APP_ORIGIN),
                (view, message, sourceOrigin, isMainFrame, reply) -> {
                    if (!isMainFrame || !APP_ORIGIN.equals(sourceOrigin.toString().replaceAll("/$", ""))) return;
                    handleBridgeMessage(message, reply);
                });
    }

    private void handleBridgeMessage(@NonNull WebMessageCompat message, @NonNull JavaScriptReplyProxy reply) {
        String raw = message.getData();
        if (raw == null || raw.length() > 24 * 1024 * 1024) return;
        int id = 0;
        try {
            JSONObject req = new JSONObject(raw);
            id = req.getInt("id");
            String cmd = req.getString("cmd");
            switch (cmd) {
                case "scan":
                    startScan(id, reply);
                    break;
                case "save":
                    replyOk(reply, id, saveFile(req.getString("name"), req.optString("mime", "text/csv"),
                            req.getString("data")));
                    break;
                default:
                    replyError(reply, id, "Comando desconhecido");
            }
        } catch (JSONException e) {
            replyError(reply, id, "Pedido inválido");
        } catch (IllegalArgumentException e) {
            replyError(reply, id, e.getMessage());
        } catch (IOException e) {
            Log.e(TAG, "Falha ao salvar arquivo", e);
            replyError(reply, id, "Não foi possível salvar o arquivo");
        }
    }

    private void startScan(int id, JavaScriptReplyProxy reply) {
        if (scanReply != null) {
            replyError(reply, id, "Já existe uma leitura em andamento");
            return;
        }
        scanReply = reply;
        scanId = id;
        ScanOptions opts = new ScanOptions()
                .setDesiredBarcodeFormats(ScanOptions.QR_CODE, ScanOptions.CODE_128, ScanOptions.CODE_39,
                        ScanOptions.EAN_13, ScanOptions.DATA_MATRIX)
                .setPrompt(getString(R.string.scan_prompt))
                .setBeepEnabled(true)
                .setOrientationLocked(false);
        scanLauncher.launch(opts);  // a biblioteca pede a permissão de câmera
    }

    /** Grava em Downloads (Android 10+) e abre o compartilhamento. Retorna onde salvou. */
    private String saveFile(String requestedName, String mime, String base64) throws IOException {
        String name = SAFE_NAME.matcher(requestedName).replaceAll("_");
        if (name.isEmpty() || name.startsWith(".") || name.length() > 120) {
            throw new IllegalArgumentException("Nome de arquivo inválido");
        }
        String type = mime.toLowerCase(Locale.ROOT).split(";")[0].trim();
        if (!ALLOWED_MIME.contains(type)) throw new IllegalArgumentException("Tipo de arquivo não permitido");
        byte[] bytes;
        try {
            bytes = Base64.decode(base64, Base64.DEFAULT);
        } catch (IllegalArgumentException e) {
            throw new IllegalArgumentException("Conteúdo do arquivo inválido");
        }
        if (bytes.length == 0 || bytes.length > MAX_FILE_BYTES) {
            throw new IllegalArgumentException("Arquivo vazio ou grande demais");
        }

        File dir = new File(getCacheDir(), "exports");
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("mkdirs");
        File[] old = dir.listFiles();  // não acumula exportações antigas no cache
        if (old != null) for (File f : old) if (!f.delete()) Log.w(TAG, "não apagou " + f.getName());
        File out = new File(dir, name);
        try (OutputStream os = new FileOutputStream(out)) {
            os.write(bytes);
        }

        String savedWhere = null;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ContentValues v = new ContentValues();
            v.put(MediaStore.Downloads.DISPLAY_NAME, name);
            v.put(MediaStore.Downloads.MIME_TYPE, type);
            v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/PB Gas Control");
            Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
            if (uri != null) {
                try (OutputStream os = getContentResolver().openOutputStream(uri)) {
                    if (os == null) throw new IOException("openOutputStream");
                    os.write(bytes);
                    savedWhere = "Downloads/PB Gas Control/" + name;
                } catch (IOException e) {
                    getContentResolver().delete(uri, null, null);
                    Log.w(TAG, "Falha ao gravar em Downloads; segue só o compartilhamento", e);
                }
            }
        }

        Uri shareUri = FileProvider.getUriForFile(this, getPackageName() + ".files", out);
        Intent send = new Intent(Intent.ACTION_SEND)
                .setType(type)
                .putExtra(Intent.EXTRA_STREAM, shareUri)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        Intent chooser = Intent.createChooser(send, getString(R.string.share_title));
        runOnUiThread(() -> {
            try {
                startActivity(chooser);
            } catch (ActivityNotFoundException e) {
                Log.w(TAG, "Sem app para compartilhar", e);
            }
        });
        return savedWhere;
    }

    private static void replyOk(JavaScriptReplyProxy reply, int id, @Nullable String result) {
        try {
            JSONObject o = new JSONObject().put("id", id).put("ok", true).put("result", result == null ? JSONObject.NULL : result);
            reply.postMessage(o.toString());
        } catch (JSONException | IllegalStateException e) {
            Log.w(TAG, "Resposta à interface falhou", e);
        }
    }

    private static void replyError(JavaScriptReplyProxy reply, int id, String error) {
        try {
            reply.postMessage(new JSONObject().put("id", id).put("ok", false).put("error", error).toString());
        } catch (JSONException | IllegalStateException e) {
            Log.w(TAG, "Resposta à interface falhou", e);
        }
    }

    // ---------------------------------------------------------------- navegação

    private void openExternally(Uri uri) {
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        if (!scheme.equals("https") && !scheme.equals("http") && !scheme.equals("mailto") && !scheme.equals("tel")) {
            Log.w(TAG, "Esquema bloqueado: " + scheme);
            return;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE));
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, R.string.no_browser, Toast.LENGTH_SHORT).show();
        }
    }

    private final class AppWebViewClient extends WebViewClientCompat {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            return assetLoader.shouldInterceptRequest(request.getUrl());
        }

        @Override
        public boolean shouldOverrideUrlLoading(@NonNull WebView view, @NonNull WebResourceRequest request) {
            Uri url = request.getUrl();
            if (ASSET_HOST.equals(url.getHost()) && "https".equals(url.getScheme())) return false;
            openExternally(url);  // DANFE, XML, links externos: navegador do sistema
            return true;
        }

        @Override
        public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            // O processo do WebView morreu (memória). Os dados estão no IndexedDB; recria a tela.
            Log.e(TAG, "Render process gone; crash=" + detail.didCrash());
            if (webView != null) {
                ((android.view.ViewGroup) webView.getParent()).removeView(webView);
                webView.destroy();
                webView = null;
            }
            recreate();
            return true;
        }
    }

    private final class AppChromeClient extends WebChromeClient {
        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
            if (!origin.startsWith(APP_ORIGIN)) {
                callback.invoke(origin, false, false);
                return;
            }
            if (ContextCompat.checkSelfPermission(MainActivity.this, Manifest.permission.ACCESS_FINE_LOCATION)
                    == PackageManager.PERMISSION_GRANTED) {
                callback.invoke(origin, true, false);
                return;
            }
            if (geoCallback != null) geoCallback.invoke(geoOrigin, false, false);
            geoCallback = callback;
            geoOrigin = origin;
            locationPermission.launch(Manifest.permission.ACCESS_FINE_LOCATION);
        }

        @Override
        public void onPermissionRequest(PermissionRequest request) {
            // Câmera via getUserMedia não é usada no app (leitor nativo); nega qualquer captura web.
            request.deny();
        }
    }

    // ---------------------------------------------------------------- assets da interface

    /** Serve somente a lista fechada de arquivos da interface, com CSP. Demais caminhos: 404. */
    private final class WebAppPathHandler implements WebViewAssetLoader.PathHandler {
        private final Map<String, String[]> files = new HashMap<>();
        private final Map<String, String> headers = new HashMap<>();

        WebAppPathHandler() {
            files.put("", new String[]{"web/index.html", "text/html"});
            files.put("index.html", new String[]{"web/index.html", "text/html"});
            files.put("static/app.js", new String[]{"web/app.js", "text/javascript"});
            files.put("static/db.js", new String[]{"web/db.js", "text/javascript"});
            files.put("static/styles.css", new String[]{"web/styles.css", "text/css"});
            files.put("static/favicon.png", new String[]{"web/favicon.png", "image/png"});
            files.put("static/icon-192.png", new String[]{"web/icon-192.png", "image/png"});
            files.put("static/brand-footer.jpg", new String[]{"web/brand-footer.jpg", "image/jpeg"});
            headers.put("Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
                            + "connect-src http: https:; object-src 'none'; base-uri 'none'; form-action 'none'; "
                            + "frame-src 'none'; worker-src 'none'; manifest-src 'none'");
            headers.put("X-Content-Type-Options", "nosniff");
            headers.put("Referrer-Policy", "no-referrer");
            headers.put("Cache-Control", "no-cache");
        }

        @Nullable
        @Override
        public WebResourceResponse handle(@NonNull String path) {
            String[] entry = files.get(path);
            if (entry == null) {
                return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found", headers,
                        new ByteArrayInputStream("not found".getBytes(StandardCharsets.UTF_8)));
            }
            try {
                InputStream in = getAssets().open(entry[0]);
                return new WebResourceResponse(entry[1], "utf-8", 200, "OK", headers, in);
            } catch (IOException e) {
                Log.e(TAG, "Asset ausente: " + entry[0], e);
                return new WebResourceResponse("text/plain", "utf-8", 500, "Error", headers,
                        new ByteArrayInputStream("asset error".getBytes(StandardCharsets.UTF_8)));
            }
        }
    }

    // ---------------------------------------------------------------- ciclo de vida

    @Override
    protected void onSaveInstanceState(@NonNull Bundle outState) {
        super.onSaveInstanceState(outState);
        if (webView != null) webView.saveState(outState);
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (webView != null) webView.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    /** Lê versão/debug sem depender de BuildConfig (desativado por padrão no AGP 8). */
    static final class BuildConfigHolder {
        private BuildConfigHolder() {}

        static String versionName(ComponentActivity a) {
            try {
                return a.getPackageManager().getPackageInfo(a.getPackageName(), 0).versionName;
            } catch (PackageManager.NameNotFoundException e) {
                return "0";
            }
        }

        static boolean isDebuggable(ComponentActivity a) {
            return (a.getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0;
        }
    }
}
