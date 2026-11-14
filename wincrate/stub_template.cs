using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("WinCrate Standalone Setup")]
[assembly: AssemblyProduct("WinCrate Software Installer")]
[assembly: AssemblyVersion("1.0.0.0")]

namespace WinCrateStub
{
    internal sealed class SubStream : Stream
    {
        private readonly Stream _baseStream;
        private readonly long _offset;
        private readonly long _length;
        private long _pos;

        public SubStream(Stream baseStream, long offset, long length)
        {
            _baseStream = baseStream;
            _offset = offset;
            _length = length;
            _pos = 0;
        }

        public override bool CanRead { get { return true; } }
        public override bool CanSeek { get { return true; } }
        public override bool CanWrite { get { return false; } }
        public override long Length { get { return _length; } }

        public override long Position
        {
            get { return _pos; }
            set { Seek(value, SeekOrigin.Begin); }
        }

        public override void Flush() { }

        public override int Read(byte[] buffer, int offset, int count)
        {
            long rem = _length - _pos;
            if (rem <= 0) return 0;
            if (count > rem) count = (int)rem;
            _baseStream.Position = _offset + _pos;
            int n = _baseStream.Read(buffer, offset, count);
            _pos += n;
            return n;
        }

        public override long Seek(long offset, SeekOrigin origin)
        {
            long target = _pos;
            if (origin == SeekOrigin.Begin) target = offset;
            else if (origin == SeekOrigin.Current) target = _pos + offset;
            else if (origin == SeekOrigin.End) target = _length + offset;

            if (target < 0) target = 0;
            if (target > _length) target = _length;
            _pos = target;
            return _pos;
        }

        public override void SetLength(long value) { throw new NotSupportedException(); }
        public override void Write(byte[] buffer, int offset, int count) { throw new NotSupportedException(); }
    }

    internal sealed class ManifestInfo
    {
        public string AppName = "Application";
        public string AppVersion = "1.0";
        public string Publisher = "";
        public string MainExeRel = "";
        public string DefaultDirName = "Application";
        public bool HasAppData = false;
        public bool HasRegistry = false;
        public bool DefaultDesktopShortcut = true;
        public bool DefaultStartMenuShortcut = true;
        public bool DefaultRegisterUninstaller = true;
        public long AppBytes = 0;
        public long AppDataBytes = 0;
    }

    internal static class PayloadReader
    {
        private const string MAGIC = "WCRATE01";

        public static SubStream OpenPayloadStream(string exePath, out FileStream outerFs)
        {
            outerFs = new FileStream(exePath, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (outerFs.Length < 24)
                throw new InvalidDataException("Setup executable does not contain a valid WinCrate payload.");

            outerFs.Position = outerFs.Length - 16;
            byte[] footer = new byte[16];
            int read = outerFs.Read(footer, 0, 16);
            if (read != 16)
                throw new InvalidDataException("Could not read package footer.");

            long offset = BitConverter.ToInt64(footer, 0);
            string magic = Encoding.ASCII.GetString(footer, 8, 8);
            if (magic != MAGIC || offset <= 0 || offset >= outerFs.Length - 16)
                throw new InvalidDataException("Invalid package signature (expected WCRATE01).");

            long length = (outerFs.Length - 16) - offset;
            return new SubStream(outerFs, offset, length);
        }

        public static ManifestInfo ReadManifest(ZipArchive zip)
        {
            ManifestInfo info = new ManifestInfo();
            ZipArchiveEntry entry = zip.GetEntry("manifest.json");
            if (entry == null) return info;

            using (Stream s = entry.Open())
            using (StreamReader sr = new StreamReader(s, Encoding.UTF8))
            {
                string json = sr.ReadToEnd();
                JavaScriptSerializer ser = new JavaScriptSerializer();
                ser.MaxJsonLength = int.MaxValue;
                Dictionary<string, object> d = ser.Deserialize<Dictionary<string, object>>(json);
                if (d == null) return info;

                info.AppName = GetStr(d, "appName", info.AppName);
                info.AppVersion = GetStr(d, "appVersion", info.AppVersion);
                info.Publisher = GetStr(d, "publisher", "");
                info.MainExeRel = GetStr(d, "mainExeRel", "");
                info.DefaultDirName = GetStr(d, "defaultDirName", "Application");
                info.HasAppData = GetBool(d, "hasAppData", false);
                info.HasRegistry = GetBool(d, "hasRegistry", false);
                info.DefaultDesktopShortcut = GetBool(d, "defaultDesktopShortcut", true);
                info.DefaultStartMenuShortcut = GetBool(d, "defaultStartMenuShortcut", true);
                info.DefaultRegisterUninstaller = GetBool(d, "defaultRegisterUninstaller", true);
                info.AppBytes = GetLong(d, "appBytes", 0);
                info.AppDataBytes = GetLong(d, "appDataBytes", 0);
            }
            return info;
        }

        private static string GetStr(Dictionary<string, object> d, string k, string defVal)
        {
            object v;
            if (d.TryGetValue(k, out v) && v != null) return v.ToString();
            return defVal;
        }

        private static bool GetBool(Dictionary<string, object> d, string k, bool defVal)
        {
            object v;
            if (d.TryGetValue(k, out v) && v != null)
            {
                bool b;
                if (bool.TryParse(v.ToString(), out b)) return b;
            }
            return defVal;
        }

        private static long GetLong(Dictionary<string, object> d, string k, long defVal)
        {
            object v;
            if (d.TryGetValue(k, out v) && v != null)
            {
                long n;
                if (long.TryParse(v.ToString(), out n)) return n;
            }
            return defVal;
        }
    }

    internal sealed class InstallOptions
    {
        public string InstallDir;
        public bool CreateDesktopShortcut;
        public bool CreateStartMenuShortcut;
        public bool RestoreAppData;
        public bool RegisterUninstaller;
        public bool ApplyRegistry = true;
        public string OverrideRoamingDir = null;
        public string OverrideLocalDir = null;
        public string OverrideRegPrefix = null;
    }

    internal static class InstallerEngine
    {
        public static void RunInstall(
            string exePath,
            ManifestInfo manifest,
            InstallOptions opts,
            Action<int, string> onProgress,
            Func<bool> isCancelled)
        {
            FileStream outerFs = null;
            try
            {
                SubStream sub = PayloadReader.OpenPayloadStream(exePath, out outerFs);
                using (ZipArchive zip = new ZipArchive(sub, ZipArchiveMode.Read))
                {
                    Directory.CreateDirectory(opts.InstallDir);

                    string roamingBase = opts.OverrideRoamingDir ?? Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                    string localBase = opts.OverrideLocalDir ?? Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);

                    List<ZipArchiveEntry> toExtract = new List<ZipArchiveEntry>();
                    ZipArchiveEntry regEntry = null;
                    ZipArchiveEntry uninstEntry = null;

                    foreach (ZipArchiveEntry e in zip.Entries)
                    {
                        string fn = e.FullName.Replace('\\', '/');
                        if (fn == "registry.json") { regEntry = e; continue; }
                        if (fn == "uninstaller.exe") { uninstEntry = e; continue; }
                        if (fn == "manifest.json") continue;
                        if (fn.EndsWith("/")) continue;

                        if (fn.StartsWith("app/"))
                        {
                            toExtract.Add(e);
                        }
                        else if (opts.RestoreAppData && (fn.StartsWith("appdata_roaming/") || fn.StartsWith("appdata_local/")))
                        {
                            toExtract.Add(e);
                        }
                    }

                    int totalCount = Math.Max(1, toExtract.Count);
                    byte[] buf = new byte[65536];

                    for (int i = 0; i < toExtract.Count; i++)
                    {
                        if (isCancelled != null && isCancelled())
                            throw new OperationCanceledException("Installation cancelled by user.");

                        ZipArchiveEntry entry = toExtract[i];
                        string fn = entry.FullName.Replace('\\', '/');
                        string targetPath = null;

                        if (fn.StartsWith("app/"))
                        {
                            string rel = fn.Substring(4).Replace('/', Path.DirectorySeparatorChar);
                            targetPath = SafeCombine(opts.InstallDir, rel);
                        }
                        else if (fn.StartsWith("appdata_roaming/"))
                        {
                            string rel = fn.Substring("appdata_roaming/".Length).Replace('/', Path.DirectorySeparatorChar);
                            targetPath = SafeCombine(roamingBase, rel);
                        }
                        else if (fn.StartsWith("appdata_local/"))
                        {
                            string rel = fn.Substring("appdata_local/".Length).Replace('/', Path.DirectorySeparatorChar);
                            targetPath = SafeCombine(localBase, rel);
                        }

                        if (targetPath == null) continue;

                        int pct = (int)((i * 88L) / totalCount);
                        if (onProgress != null && (i % 5 == 0 || i == toExtract.Count - 1))
                        {
                            onProgress(pct, "Extracting " + Path.GetFileName(targetPath));
                        }

                        string dir = Path.GetDirectoryName(targetPath);
                        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

                        using (Stream inStream = entry.Open())
                        using (FileStream outStream = new FileStream(targetPath, FileMode.Create, FileAccess.Write, FileShare.None))
                        {
                            int n;
                            while ((n = inStream.Read(buf, 0, buf.Length)) > 0)
                            {
                                outStream.Write(buf, 0, n);
                            }
                        }
                    }

                    // Extract uninstaller.exe if available
                    string uninstPath = Path.Combine(opts.InstallDir, "Uninstall.exe");
                    if (uninstEntry != null)
                    {
                        using (Stream inS = uninstEntry.Open())
                        using (FileStream outS = new FileStream(uninstPath, FileMode.Create, FileAccess.Write))
                        {
                            inS.CopyTo(outS);
                        }
                    }

                    // Restore tokenized Registry entries
                    if (opts.ApplyRegistry && regEntry != null)
                    {
                        if (onProgress != null) onProgress(91, "Restoring application registry settings...");
                        ApplyRegistrySnapshot(regEntry, opts.InstallDir, opts.OverrideRegPrefix);
                    }

                    // Create shortcuts
                    List<string> createdShortcuts = new List<string>();
                    string mainExeFull = !string.IsNullOrEmpty(manifest.MainExeRel)
                        ? Path.Combine(opts.InstallDir, manifest.MainExeRel.Replace('/', Path.DirectorySeparatorChar))
                        : "";

                    if (!string.IsNullOrEmpty(mainExeFull) && File.Exists(mainExeFull))
                    {
                        string safeTitle = SanitizeFileName(manifest.AppName);
                        if (opts.CreateDesktopShortcut)
                        {
                            if (onProgress != null) onProgress(95, "Creating Desktop shortcut...");
                            string desk = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                            string lnk = Path.Combine(desk, safeTitle + ".lnk");
                            if (CreateShortcut(lnk, mainExeFull, opts.InstallDir, manifest.AppName))
                                createdShortcuts.Add(lnk);
                        }
                        if (opts.CreateStartMenuShortcut)
                        {
                            if (onProgress != null) onProgress(97, "Creating Start Menu shortcut...");
                            string progs = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                            string lnk = Path.Combine(progs, safeTitle + ".lnk");
                            if (CreateShortcut(lnk, mainExeFull, opts.InstallDir, manifest.AppName))
                                createdShortcuts.Add(lnk);
                        }
                    }

                    // Register Uninstaller & write install receipt
                    string uninstRegKey = "";
                    if (opts.RegisterUninstaller && File.Exists(uninstPath))
                    {
                        string slug = SanitizeKeyName(manifest.AppName);
                        uninstRegKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\WinCrate_" + slug;
                        try
                        {
                            using (RegistryKey rk = Registry.CurrentUser.CreateSubKey(uninstRegKey))
                            {
                                if (rk != null)
                                {
                                    rk.SetValue("DisplayName", manifest.AppName, RegistryValueKind.String);
                                    rk.SetValue("DisplayVersion", manifest.AppVersion, RegistryValueKind.String);
                                    rk.SetValue("Publisher", string.IsNullOrEmpty(manifest.Publisher) ? "WinCrate Package" : manifest.Publisher, RegistryValueKind.String);
                                    rk.SetValue("InstallLocation", opts.InstallDir, RegistryValueKind.String);
                                    if (!string.IsNullOrEmpty(mainExeFull) && File.Exists(mainExeFull))
                                        rk.SetValue("DisplayIcon", mainExeFull, RegistryValueKind.String);
                                    rk.SetValue("UninstallString", "\"" + uninstPath + "\"", RegistryValueKind.String);
                                    rk.SetValue("NoModify", 1, RegistryValueKind.DWord);
                                    rk.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                                    rk.SetValue("EstimatedSize", (int)Math.Max(1L, manifest.AppBytes / 1024L), RegistryValueKind.DWord);
                                }
                            }
                        }
                        catch { }
                    }

                    // Write receipt for clean uninstall
                    try
                    {
                        JavaScriptSerializer ser = new JavaScriptSerializer();
                        Dictionary<string, object> receipt = new Dictionary<string, object>();
                        receipt["appName"] = manifest.AppName;
                        receipt["installDir"] = opts.InstallDir;
                        receipt["shortcuts"] = createdShortcuts;
                        receipt["uninstallRegKey"] = uninstRegKey;
                        File.WriteAllText(
                            Path.Combine(opts.InstallDir, "wincrate_receipt.json"),
                            ser.Serialize(receipt),
                            Encoding.UTF8);
                    }
                    catch { }

                    if (onProgress != null) onProgress(100, "Installation complete.");
                }
            }
            finally
            {
                if (outerFs != null) outerFs.Dispose();
            }
        }

        private static string SafeCombine(string rootDir, string relPath)
        {
            string fullRoot = Path.GetFullPath(rootDir);
            if (!fullRoot.EndsWith(Path.DirectorySeparatorChar.ToString()))
                fullRoot += Path.DirectorySeparatorChar;
            string combined = Path.GetFullPath(Path.Combine(fullRoot, relPath));
            if (!combined.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
                return null;
            return combined;
        }

        private static void ApplyRegistrySnapshot(ZipArchiveEntry regEntry, string installDir, string overridePrefix)
        {
            try
            {
                string json;
                using (Stream s = regEntry.Open())
                using (StreamReader sr = new StreamReader(s, Encoding.UTF8))
                {
                    json = sr.ReadToEnd();
                }

                JavaScriptSerializer ser = new JavaScriptSerializer();
                ser.MaxJsonLength = int.MaxValue;
                ArrayList items = ser.Deserialize<ArrayList>(json);
                if (items == null) return;

                string userProf = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

                foreach (object itemObj in items)
                {
                    Dictionary<string, object> node = itemObj as Dictionary<string, object>;
                    if (node == null || !node.ContainsKey("subkey")) continue;
                    string subkey = node["subkey"] != null ? node["subkey"].ToString() : "";
                    if (string.IsNullOrEmpty(subkey)) continue;

                    if (!string.IsNullOrEmpty(overridePrefix))
                    {
                        subkey = overridePrefix.TrimEnd('\\') + "\\" + subkey;
                    }

                    try
                    {
                        using (RegistryKey rk = Registry.CurrentUser.CreateSubKey(subkey))
                        {
                            if (rk == null || !node.ContainsKey("values")) continue;
                            ArrayList vals = node["values"] as ArrayList;
                            if (vals == null) continue;

                            foreach (object vObj in vals)
                            {
                                Dictionary<string, object> vd = vObj as Dictionary<string, object>;
                                if (vd == null || !vd.ContainsKey("kind")) continue;
                                string vName = vd.ContainsKey("name") && vd["name"] != null ? vd["name"].ToString() : "";
                                string kind = vd["kind"].ToString();
                                object rawVal = vd.ContainsKey("value") ? vd["value"] : null;
                                if (rawVal == null) continue;

                                if (kind == "String" || kind == "ExpandString")
                                {
                                    string strVal = Detokenize(rawVal.ToString(), installDir, userProf);
                                    rk.SetValue(vName, strVal, kind == "ExpandString" ? RegistryValueKind.ExpandString : RegistryValueKind.String);
                                }
                                else if (kind == "DWord")
                                {
                                    int dw;
                                    if (int.TryParse(rawVal.ToString(), out dw))
                                        rk.SetValue(vName, dw, RegistryValueKind.DWord);
                                }
                                else if (kind == "QWord")
                                {
                                    long qw;
                                    if (long.TryParse(rawVal.ToString(), out qw))
                                        rk.SetValue(vName, qw, RegistryValueKind.QWord);
                                }
                                else if (kind == "MultiString")
                                {
                                    ArrayList arr = rawVal as ArrayList;
                                    if (arr != null)
                                    {
                                        string[] strs = new string[arr.Count];
                                        for (int i = 0; i < arr.Count; i++)
                                            strs[i] = Detokenize(arr[i] != null ? arr[i].ToString() : "", installDir, userProf);
                                        rk.SetValue(vName, strs, RegistryValueKind.MultiString);
                                    }
                                }
                                else if (kind == "Binary")
                                {
                                    byte[] bytes = Convert.FromBase64String(rawVal.ToString());
                                    rk.SetValue(vName, bytes, RegistryValueKind.Binary);
                                }
                            }
                        }
                    }
                    catch { }
                }
            }
            catch { }
        }

        private static string Detokenize(string input, string installDir, string userProf)
        {
            if (string.IsNullOrEmpty(input)) return "";
            return input
                .Replace("{{INSTALL_DIR}}", installDir)
                .Replace("{{USER_PROFILE}}", userProf);
        }

        private static bool CreateShortcut(string lnkPath, string targetExe, string workingDir, string description)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return false;
                object shell = Activator.CreateInstance(shellType);
                object shortcut = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { lnkPath });
                Type scType = shortcut.GetType();
                scType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { targetExe });
                scType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { workingDir });
                scType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { description });
                scType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { targetExe + ",0" });
                scType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
                return File.Exists(lnkPath);
            }
            catch
            {
                return false;
            }
        }

        public static string SanitizeFileName(string name)
        {
            if (string.IsNullOrEmpty(name)) return "Application";
            foreach (char c in Path.GetInvalidFileNameChars())
                name = name.Replace(c, '_');
            return name.Trim();
        }

        public static string SanitizeKeyName(string name)
        {
            StringBuilder sb = new StringBuilder();
            foreach (char c in (name ?? "App"))
            {
                if (char.IsLetterOrDigit(c) || c == '_' || c == '-') sb.Append(c);
                else sb.Append('_');
            }
            return sb.Length > 0 ? sb.ToString() : "App";
        }

        public static string FormatBytes(long bytes)
        {
            if (bytes < 1024) return bytes + " B";
            double kb = bytes / 1024.0;
            if (kb < 1024) return kb.ToString("0.0") + " KB";
            double mb = kb / 1024.0;
            if (mb < 1024) return mb.ToString("0.0") + " MB";
            double gb = mb / 1024.0;
            return gb.ToString("0.00") + " GB";
        }
    }

    internal sealed class SetupForm : Form
    {
        private readonly string _exePath;
        private readonly ManifestInfo _manifest;

        private TextBox _dirBox;
        private Button _browseBtn;
        private CheckBox _chkDesktop;
        private CheckBox _chkStartMenu;
        private CheckBox _chkAppData;
        private CheckBox _chkUninstall;
        private CheckBox _chkLaunch;
        private ProgressBar _progress;
        private Label _statusLabel;
        private Button _installBtn;
        private Button _cancelBtn;

        private volatile bool _installing = false;
        private volatile bool _cancelled = false;
        private volatile bool _finished = false;

        public SetupForm(string exePath, ManifestInfo manifest)
        {
            _exePath = exePath;
            _manifest = manifest;

            Text = manifest.AppName + " Setup";
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            ClientSize = new Size(540, 415);
            BackColor = Color.FromArgb(236, 234, 228); // #ECEAE4 linen ground
            Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            try
            {
                Icon selfIcon = Icon.ExtractAssociatedIcon(exePath);
                if (selfIcon != null) Icon = selfIcon;
            }
            catch { }

            BuildUi();
        }

        private void BuildUi()
        {
            Panel header = new Panel();
            header.BackColor = Color.FromArgb(247, 246, 242);
            header.Location = new Point(0, 0);
            header.Size = new Size(540, 86);
            Controls.Add(header);

            PictureBox pic = new PictureBox();
            pic.Location = new Point(22, 20);
            pic.Size = new Size(44, 44);
            pic.SizeMode = PictureBoxSizeMode.StretchImage;
            if (Icon != null) pic.Image = Icon.ToBitmap();
            header.Controls.Add(pic);

            Label titleLbl = new Label();
            titleLbl.Text = _manifest.AppName;
            titleLbl.Font = new Font("Segoe UI Semibold", 13.5f, FontStyle.Bold);
            titleLbl.ForeColor = Color.FromArgb(25, 25, 23);
            titleLbl.Location = new Point(78, 18);
            titleLbl.Size = new Size(440, 28);
            header.Controls.Add(titleLbl);

            string meta = "Version " + _manifest.AppVersion;
            if (!string.IsNullOrEmpty(_manifest.Publisher)) meta += "  |  " + _manifest.Publisher;
            long totalBytes = _manifest.AppBytes + (_manifest.HasAppData ? _manifest.AppDataBytes : 0);
            if (totalBytes > 0) meta += "  |  " + InstallerEngine.FormatBytes(totalBytes);

            Label subLbl = new Label();
            subLbl.Text = meta;
            subLbl.ForeColor = Color.FromArgb(83, 81, 75);
            subLbl.Location = new Point(80, 48);
            subLbl.Size = new Size(440, 22);
            header.Controls.Add(subLbl);

            Panel divider = new Panel();
            divider.BackColor = Color.FromArgb(210, 206, 196);
            divider.Location = new Point(0, 86);
            divider.Size = new Size(540, 1);
            Controls.Add(divider);

            Label dirLbl = new Label();
            dirLbl.Text = "Destination folder";
            dirLbl.Font = new Font("Segoe UI Semibold", 9.5f, FontStyle.Bold);
            dirLbl.ForeColor = Color.FromArgb(25, 25, 23);
            dirLbl.Location = new Point(22, 104);
            dirLbl.Size = new Size(300, 20);
            Controls.Add(dirLbl);

            string localProgs = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs");
            string defaultDir = Path.Combine(localProgs, InstallerEngine.SanitizeFileName(_manifest.DefaultDirName));

            _dirBox = new TextBox();
            _dirBox.Text = defaultDir;
            _dirBox.Location = new Point(22, 128);
            _dirBox.Size = new Size(402, 27);
            Controls.Add(_dirBox);

            _browseBtn = new Button();
            _browseBtn.Text = "Browse...";
            _browseBtn.FlatStyle = FlatStyle.System;
            _browseBtn.Location = new Point(432, 126);
            _browseBtn.Size = new Size(86, 29);
            _browseBtn.Click += OnBrowseClick;
            Controls.Add(_browseBtn);

            Label optLbl = new Label();
            optLbl.Text = "Setup options";
            optLbl.Font = new Font("Segoe UI Semibold", 9.5f, FontStyle.Bold);
            optLbl.ForeColor = Color.FromArgb(25, 25, 23);
            optLbl.Location = new Point(22, 170);
            optLbl.Size = new Size(300, 20);
            Controls.Add(optLbl);

            _chkDesktop = new CheckBox();
            _chkDesktop.Text = "Create Desktop shortcut";
            _chkDesktop.Checked = _manifest.DefaultDesktopShortcut && !string.IsNullOrEmpty(_manifest.MainExeRel);
            _chkDesktop.Enabled = !string.IsNullOrEmpty(_manifest.MainExeRel);
            _chkDesktop.Location = new Point(24, 196);
            _chkDesktop.Size = new Size(480, 24);
            Controls.Add(_chkDesktop);

            _chkStartMenu = new CheckBox();
            _chkStartMenu.Text = "Create Start Menu shortcut";
            _chkStartMenu.Checked = _manifest.DefaultStartMenuShortcut && !string.IsNullOrEmpty(_manifest.MainExeRel);
            _chkStartMenu.Enabled = !string.IsNullOrEmpty(_manifest.MainExeRel);
            _chkStartMenu.Location = new Point(24, 222);
            _chkStartMenu.Size = new Size(480, 24);
            Controls.Add(_chkStartMenu);

            _chkAppData = new CheckBox();
            if (_manifest.HasAppData)
            {
                _chkAppData.Text = "Restore bundled AppData settings & plugins (" + InstallerEngine.FormatBytes(_manifest.AppDataBytes) + ")";
                _chkAppData.Checked = true;
                _chkAppData.Enabled = true;
            }
            else
            {
                _chkAppData.Text = "Restore AppData settings (none bundled in this package)";
                _chkAppData.Checked = false;
                _chkAppData.Enabled = false;
            }
            _chkAppData.Location = new Point(24, 248);
            _chkAppData.Size = new Size(490, 24);
            Controls.Add(_chkAppData);

            _chkUninstall = new CheckBox();
            _chkUninstall.Text = "Register in Windows Installed Apps (adds Uninstaller)";
            _chkUninstall.Checked = _manifest.DefaultRegisterUninstaller;
            _chkUninstall.Location = new Point(24, 274);
            _chkUninstall.Size = new Size(490, 24);
            Controls.Add(_chkUninstall);

            _chkLaunch = new CheckBox();
            _chkLaunch.Text = "Launch " + _manifest.AppName + " after setup finishes";
            _chkLaunch.Checked = !string.IsNullOrEmpty(_manifest.MainExeRel);
            _chkLaunch.Visible = false;
            _chkLaunch.Location = new Point(24, 304);
            _chkLaunch.Size = new Size(490, 24);
            Controls.Add(_chkLaunch);

            _statusLabel = new Label();
            _statusLabel.Text = "Ready to install offline.";
            _statusLabel.ForeColor = Color.FromArgb(83, 81, 75);
            _statusLabel.Location = new Point(22, 312);
            _statusLabel.Size = new Size(496, 20);
            Controls.Add(_statusLabel);

            _progress = new ProgressBar();
            _progress.Minimum = 0;
            _progress.Maximum = 100;
            _progress.Value = 0;
            _progress.Location = new Point(22, 335);
            _progress.Size = new Size(496, 18);
            Controls.Add(_progress);

            _installBtn = new Button();
            _installBtn.Text = "Install";
            _installBtn.BackColor = Color.FromArgb(181, 62, 25); // #B53E19 rust signal
            _installBtn.ForeColor = Color.White;
            _installBtn.FlatStyle = FlatStyle.Flat;
            _installBtn.FlatAppearance.BorderSize = 0;
            _installBtn.Font = new Font("Segoe UI Semibold", 9.5f, FontStyle.Bold);
            _installBtn.Location = new Point(316, 368);
            _installBtn.Size = new Size(106, 34);
            _installBtn.Click += OnInstallClick;
            Controls.Add(_installBtn);

            _cancelBtn = new Button();
            _cancelBtn.Text = "Cancel";
            _cancelBtn.FlatStyle = FlatStyle.System;
            _cancelBtn.Location = new Point(430, 368);
            _cancelBtn.Size = new Size(88, 34);
            _cancelBtn.Click += OnCancelClick;
            Controls.Add(_cancelBtn);
        }

        private void OnBrowseClick(object sender, EventArgs e)
        {
            using (FolderBrowserDialog fbd = new FolderBrowserDialog())
            {
                fbd.Description = "Choose where to install " + _manifest.AppName;
                fbd.SelectedPath = _dirBox.Text;
                if (fbd.ShowDialog(this) == DialogResult.OK && !string.IsNullOrEmpty(fbd.SelectedPath))
                {
                    string leaf = InstallerEngine.SanitizeFileName(_manifest.DefaultDirName);
                    string chosen = fbd.SelectedPath;
                    if (!chosen.EndsWith(leaf, StringComparison.OrdinalIgnoreCase))
                        chosen = Path.Combine(chosen, leaf);
                    _dirBox.Text = chosen;
                }
            }
        }

        private void OnInstallClick(object sender, EventArgs e)
        {
            if (_finished)
            {
                if (_chkLaunch.Visible && _chkLaunch.Checked && !string.IsNullOrEmpty(_manifest.MainExeRel))
                {
                    string exeToRun = Path.Combine(_dirBox.Text.Trim(), _manifest.MainExeRel.Replace('/', Path.DirectorySeparatorChar));
                    if (File.Exists(exeToRun))
                    {
                        try
                        {
                            ProcessStartInfo psi = new ProcessStartInfo(exeToRun);
                            psi.WorkingDirectory = Path.GetDirectoryName(exeToRun);
                            Process.Start(psi);
                        }
                        catch { }
                    }
                }
                Close();
                return;
            }

            if (_installing) return;

            string targetDir = _dirBox.Text.Trim();
            if (string.IsNullOrEmpty(targetDir))
            {
                MessageBox.Show(this, "Enter a valid destination folder.", "Destination Required", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            _installing = true;
            _cancelled = false;
            _dirBox.Enabled = false;
            _browseBtn.Enabled = false;
            _chkDesktop.Enabled = false;
            _chkStartMenu.Enabled = false;
            _chkAppData.Enabled = false;
            _chkUninstall.Enabled = false;
            _installBtn.Enabled = false;

            InstallOptions opts = new InstallOptions();
            opts.InstallDir = targetDir;
            opts.CreateDesktopShortcut = _chkDesktop.Checked;
            opts.CreateStartMenuShortcut = _chkStartMenu.Checked;
            opts.RestoreAppData = _chkAppData.Checked;
            opts.RegisterUninstaller = _chkUninstall.Checked;

            Thread worker = new Thread(delegate ()
            {
                try
                {
                    InstallerEngine.RunInstall(
                        _exePath,
                        _manifest,
                        opts,
                        delegate (int pct, string msg)
                        {
                            BeginInvoke((MethodInvoker)delegate ()
                            {
                                _progress.Value = Math.Max(0, Math.Min(100, pct));
                                _statusLabel.Text = msg;
                            });
                        },
                        delegate () { return _cancelled; });

                    BeginInvoke((MethodInvoker)delegate ()
                    {
                        _installing = false;
                        _finished = true;
                        _progress.Value = 100;
                        _statusLabel.Text = _manifest.AppName + " was installed to " + opts.InstallDir;
                        _installBtn.Text = "Finish";
                        _installBtn.Enabled = true;
                        _cancelBtn.Visible = false;
                        _installBtn.Location = new Point(412, 368);
                        if (!string.IsNullOrEmpty(_manifest.MainExeRel))
                        {
                            _chkLaunch.Location = new Point(22, 373);
                            _chkLaunch.Size = new Size(375, 24);
                            _chkLaunch.Visible = true;
                        }
                    });
                }
                catch (Exception ex)
                {
                    BeginInvoke((MethodInvoker)delegate ()
                    {
                        _installing = false;
                        _statusLabel.Text = "Setup stopped: " + ex.Message;
                        _dirBox.Enabled = true;
                        _browseBtn.Enabled = true;
                        _installBtn.Enabled = true;
                        if (!(ex is OperationCanceledException))
                        {
                            MessageBox.Show(this, ex.Message, "Installation Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        }
                    });
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }

        private void OnCancelClick(object sender, EventArgs e)
        {
            if (_installing)
            {
                _cancelled = true;
                _statusLabel.Text = "Cancelling...";
            }
            else
            {
                Close();
            }
        }
    }

    internal static class Program
    {
        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [STAThread]
        public static int Main(string[] args)
        {
            try { SetProcessDPIAware(); } catch { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string exePath = Application.ExecutablePath;
            bool silent = false;
            string customDir = null;
            bool noShortcuts = false;
            bool noUninstall = false;
            bool noRegistry = false;
            string roamOverride = null;
            string localOverride = null;
            string regPrefixOverride = null;

            if (args != null)
            {
                foreach (string a in args)
                {
                    if (string.Equals(a, "--silent", StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(a, "/S", StringComparison.OrdinalIgnoreCase))
                        silent = true;
                    else if (a.StartsWith("--dir=", StringComparison.OrdinalIgnoreCase))
                        customDir = a.Substring(6).Trim('"');
                    else if (string.Equals(a, "--no-shortcuts", StringComparison.OrdinalIgnoreCase))
                        noShortcuts = true;
                    else if (string.Equals(a, "--no-uninstaller", StringComparison.OrdinalIgnoreCase))
                        noUninstall = true;
                    else if (string.Equals(a, "--no-registry", StringComparison.OrdinalIgnoreCase))
                        noRegistry = true;
                    else if (a.StartsWith("--appdata-roaming=", StringComparison.OrdinalIgnoreCase))
                        roamOverride = a.Substring("--appdata-roaming=".Length).Trim('"');
                    else if (a.StartsWith("--appdata-local=", StringComparison.OrdinalIgnoreCase))
                        localOverride = a.Substring("--appdata-local=".Length).Trim('"');
                    else if (a.StartsWith("--reg-prefix=", StringComparison.OrdinalIgnoreCase))
                        regPrefixOverride = a.Substring("--reg-prefix=".Length).Trim('"');
                }
            }

            ManifestInfo manifest;
            FileStream fs = null;
            try
            {
                SubStream sub = PayloadReader.OpenPayloadStream(exePath, out fs);
                using (ZipArchive zip = new ZipArchive(sub, ZipArchiveMode.Read))
                {
                    manifest = PayloadReader.ReadManifest(zip);
                }
            }
            catch (Exception ex)
            {
                if (!silent)
                    MessageBox.Show("Unable to open setup package:\n" + ex.Message, "WinCrate Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
                else
                    Console.Error.WriteLine(ex.Message);
                return 2;
            }
            finally
            {
                if (fs != null) fs.Dispose();
            }

            if (silent)
            {
                try
                {
                    string localProgs = Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                        "Programs");
                    InstallOptions opts = new InstallOptions();
                    opts.InstallDir = !string.IsNullOrEmpty(customDir)
                        ? customDir
                        : Path.Combine(localProgs, InstallerEngine.SanitizeFileName(manifest.DefaultDirName));
                    opts.CreateDesktopShortcut = !noShortcuts && manifest.DefaultDesktopShortcut;
                    opts.CreateStartMenuShortcut = !noShortcuts && manifest.DefaultStartMenuShortcut;
                    opts.RestoreAppData = manifest.HasAppData;
                    opts.RegisterUninstaller = !noUninstall && manifest.DefaultRegisterUninstaller;
                    opts.ApplyRegistry = !noRegistry;
                    opts.OverrideRoamingDir = roamOverride;
                    opts.OverrideLocalDir = localOverride;
                    opts.OverrideRegPrefix = regPrefixOverride;

                    InstallerEngine.RunInstall(exePath, manifest, opts, null, null);
                    return 0;
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine(ex.ToString());
                    return 1;
                }
            }

            Application.Run(new SetupForm(exePath, manifest));
            return 0;
        }
    }
}
