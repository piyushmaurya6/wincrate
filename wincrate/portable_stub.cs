using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("WinCrate Portable")]
[assembly: AssemblyDescription("WinCrate — Standalone Offline Windows Software Packager")]
[assembly: AssemblyProduct("WinCrate")]
[assembly: AssemblyVersion("1.0.0.0")]

namespace WinCratePortable
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

    internal sealed class SplashProgressForm : Form
    {
        private readonly Label _statusLabel;
        private readonly Panel _barTrack;
        private readonly Panel _barFill;

        public SplashProgressForm()
        {
            Text = "WinCrate";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            ControlBox = false;
            ClientSize = new Size(420, 118);
            BackColor = Color.FromArgb(236, 234, 228); // #ECEAE4 linen canvas
            Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            Label title = new Label();
            title.Text = "WinCrate — Preparing Standalone Engine";
            title.Font = new Font("Segoe UI Semibold", 10.5f, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(25, 25, 23);
            title.AutoSize = false;
            title.SetBounds(22, 20, 376, 24);

            _statusLabel = new Label();
            _statusLabel.Text = "Unpacking self-contained runtime (first launch on this PC)...";
            _statusLabel.ForeColor = Color.FromArgb(83, 81, 75);
            _statusLabel.AutoSize = false;
            _statusLabel.SetBounds(22, 48, 376, 20);

            _barTrack = new Panel();
            _barTrack.BackColor = Color.FromArgb(210, 206, 196);
            _barTrack.SetBounds(22, 78, 376, 10);

            _barFill = new Panel();
            _barFill.BackColor = Color.FromArgb(181, 62, 25); // #B53E19 rust-orange press action
            _barFill.SetBounds(0, 0, 8, 10);
            _barTrack.Controls.Add(_barFill);

            Controls.Add(title);
            Controls.Add(_statusLabel);
            Controls.Add(_barTrack);
        }

        public void SetProgress(int percent, string message)
        {
            if (InvokeRequired)
            {
                BeginInvoke(new Action<int, string>(SetProgress), percent, message);
                return;
            }
            if (percent < 2) percent = 2;
            if (percent > 100) percent = 100;
            _barFill.Width = (int)Math.Round(376.0 * percent / 100.0);
            if (!string.IsNullOrEmpty(message))
            {
                _statusLabel.Text = message;
            }
        }
    }

    internal static class Program
    {
        private const string MAGIC = "WCRATE01";

        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [STAThread]
        public static int Main(string[] args)
        {
            try { SetProcessDPIAware(); } catch { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            bool cliMode = false;
            bool forceReextract = false;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--self-test" || args[i] == "--serve-only" || args[i] == "--silent")
                {
                    cliMode = true;
                }
                if (args[i] == "--reextract")
                {
                    forceReextract = true;
                }
            }

            string exePath = Process.GetCurrentProcess().MainModule.FileName;
            long payloadOffset;
            long payloadLen;
            string fingerprint;

            try
            {
                ReadPayloadHeader(exePath, out payloadOffset, out payloadLen, out fingerprint);
            }
            catch (Exception ex)
            {
                if (!cliMode)
                {
                    MessageBox.Show("Standalone package payload could not be read:\n" + ex.Message, "WinCrate", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
                else
                {
                    Console.Error.WriteLine("Payload error: " + ex.Message);
                }
                return 2;
            }

            string cacheDir = ResolveRuntimeCacheDir(fingerprint, forceReextract);
            bool createdNew;
            using (Mutex mutex = new Mutex(true, @"Local\WinCratePortable_" + fingerprint, out createdNew))
            {
                try
                {
                    mutex.WaitOne(60000);
                }
                catch (AbandonedMutexException) { }

                try
                {
                    if (forceReextract || !IsRuntimeReady(cacheDir))
                    {
                        if (cliMode)
                        {
                            ExtractPayload(exePath, payloadOffset, payloadLen, cacheDir, null);
                        }
                        else
                        {
                            ExtractWithSplash(exePath, payloadOffset, payloadLen, cacheDir);
                        }
                    }
                }
                catch (Exception ex)
                {
                    if (!cliMode)
                    {
                        MessageBox.Show("Failed to initialize WinCrate standalone runtime:\n" + ex.Message, "WinCrate", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    }
                    else
                    {
                        Console.Error.WriteLine("Extraction error: " + ex.Message);
                    }
                    return 3;
                }
                finally
                {
                    try { mutex.ReleaseMutex(); } catch { }
                }
            }

            return LaunchExtractedApp(cacheDir, args, cliMode);
        }

        private static void ReadPayloadHeader(string exePath, out long offset, out long length, out string fingerprint)
        {
            using (FileStream fs = new FileStream(exePath, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (fs.Length < 24)
                {
                    throw new InvalidDataException("Executable is too small to contain an embedded runtime.");
                }
                fs.Seek(-16, SeekOrigin.End);
                byte[] footer = new byte[16];
                ReadExact(fs, footer, 16);
                string magic = Encoding.ASCII.GetString(footer, 8, 8);
                if (magic != MAGIC)
                {
                    throw new InvalidDataException("Missing WCRATE01 standalone runtime footer.");
                }
                offset = BitConverter.ToInt64(footer, 0);
                length = (fs.Length - 16) - offset;
                if (offset <= 0 || length <= 0)
                {
                    throw new InvalidDataException("Invalid embedded payload bounds.");
                }

                // Fingerprint last 32 KB of ZIP central directory + file size + offset
                int sampleSize = (int)Math.Min(32768L, length);
                byte[] sample = new byte[sampleSize + 16];
                Buffer.BlockCopy(BitConverter.GetBytes(fs.Length), 0, sample, 0, 8);
                Buffer.BlockCopy(BitConverter.GetBytes(offset), 0, sample, 8, 8);
                fs.Seek((fs.Length - 16) - sampleSize, SeekOrigin.Begin);
                ReadExact(fs, sample, 16, sampleSize);

                using (SHA256 sha = SHA256.Create())
                {
                    byte[] hash = sha.ComputeHash(sample);
                    StringBuilder sb = new StringBuilder(12);
                    for (int i = 0; i < 6; i++)
                    {
                        sb.Append(hash[i].ToString("x2"));
                    }
                    fingerprint = sb.ToString();
                }
            }
        }

        private static void ReadExact(Stream s, byte[] buf, int count)
        {
            ReadExact(s, buf, 0, count);
        }

        private static void ReadExact(Stream s, byte[] buf, int start, int count)
        {
            int done = 0;
            while (done < count)
            {
                int n = s.Read(buf, start + done, count - done);
                if (n <= 0) throw new EndOfStreamException();
                done += n;
            }
        }

        private static bool IsRuntimeReady(string dir)
        {
            if (string.IsNullOrEmpty(dir) || !Directory.Exists(dir)) return false;
            string ready = Path.Combine(dir, ".ready");
            string pyw = Path.Combine(dir, @"runtime\pythonw.exe");
            string appPy = Path.Combine(dir, @"app\app.py");
            return File.Exists(ready) && File.Exists(pyw) && File.Exists(appPy);
        }

        private static string ResolveRuntimeCacheDir(string fingerprint, bool forceReextract)
        {
            string folderName = "wc_" + fingerprint;
            string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string primary = Path.Combine(localApp, Path.Combine(@"WinCrate\Runtime", folderName));
            if (!forceReextract && IsRuntimeReady(primary))
            {
                return primary;
            }

            // Check if already extracted on a secondary fixed drive
            DriveInfo[] drives = DriveInfo.GetDrives();
            if (!forceReextract)
            {
                for (int i = 0; i < drives.Length; i++)
                {
                    try
                    {
                        if (drives[i].DriveType == DriveType.Fixed && drives[i].IsReady)
                        {
                            string alt = Path.Combine(drives[i].RootDirectory.FullName, Path.Combine(@"WinCrate_Packages\.wincrate_runtime", folderName));
                            if (IsRuntimeReady(alt)) return alt;
                        }
                    }
                    catch { }
                }
            }

            // Prefer LocalAppData when its drive has >= 450 MB free; otherwise pick fixed drive with most free space
            long localFree = GetDriveFreeBytes(localApp);
            if (localFree >= 450L * 1024L * 1024L)
            {
                return primary;
            }

            string bestRoot = null;
            long bestFree = localFree;
            for (int i = 0; i < drives.Length; i++)
            {
                try
                {
                    if (drives[i].DriveType == DriveType.Fixed && drives[i].IsReady)
                    {
                        long f = drives[i].AvailableFreeSpace;
                        if (f > bestFree)
                        {
                            bestFree = f;
                            bestRoot = drives[i].RootDirectory.FullName;
                        }
                    }
                }
                catch { }
            }

            if (!string.IsNullOrEmpty(bestRoot))
            {
                return Path.Combine(bestRoot, Path.Combine(@"WinCrate_Packages\.wincrate_runtime", folderName));
            }
            return primary;
        }

        private static long GetDriveFreeBytes(string path)
        {
            try
            {
                string root = Path.GetPathRoot(Path.GetFullPath(path));
                DriveInfo di = new DriveInfo(root);
                if (di.IsReady) return di.AvailableFreeSpace;
            }
            catch { }
            return 0;
        }

        private static void ExtractWithSplash(string exePath, long offset, long length, string destDir)
        {
            Exception workerError = null;
            using (SplashProgressForm splash = new SplashProgressForm())
            {
                Thread worker = new Thread(delegate()
                {
                    try
                    {
                        ExtractPayload(exePath, offset, length, destDir, delegate(int pct, string msg)
                        {
                            splash.SetProgress(pct, msg);
                        });
                    }
                    catch (Exception ex)
                    {
                        workerError = ex;
                    }
                    finally
                    {
                        try
                        {
                            splash.BeginInvoke(new Action(delegate() { splash.Close(); }));
                        }
                        catch { }
                    }
                });
                worker.IsBackground = true;
                splash.Shown += delegate { worker.Start(); };
                Application.Run(splash);
                worker.Join();
            }

            if (workerError != null)
            {
                throw workerError;
            }
        }

        private static void ExtractPayload(string exePath, long offset, long length, string destDir, Action<int, string> onProgress)
        {
            string readyMarker = Path.Combine(destDir, ".ready");
            if (File.Exists(readyMarker))
            {
                try { File.Delete(readyMarker); } catch { }
            }
            Directory.CreateDirectory(destDir);
            string fullDestRoot = Path.GetFullPath(destDir);
            if (!fullDestRoot.EndsWith(Path.DirectorySeparatorChar.ToString()))
            {
                fullDestRoot += Path.DirectorySeparatorChar;
            }

            byte[] copyBuf = new byte[65536];
            using (FileStream fs = new FileStream(exePath, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                SubStream sub = new SubStream(fs, offset, length);
                using (ZipArchive zip = new ZipArchive(sub, ZipArchiveMode.Read, false))
                {
                    int total = zip.Entries.Count;
                    if (total < 1) total = 1;
                    int idx = 0;

                    foreach (ZipArchiveEntry entry in zip.Entries)
                    {
                        idx++;
                        string rel = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                        if (string.IsNullOrEmpty(rel)) continue;

                        string outPath = Path.GetFullPath(Path.Combine(destDir, rel));
                        if (!outPath.StartsWith(fullDestRoot, StringComparison.OrdinalIgnoreCase))
                        {
                            continue;
                        }

                        if (entry.FullName.EndsWith("/") || entry.FullName.EndsWith("\\"))
                        {
                            Directory.CreateDirectory(outPath);
                            continue;
                        }

                        string parent = Path.GetDirectoryName(outPath);
                        if (!string.IsNullOrEmpty(parent))
                        {
                            Directory.CreateDirectory(parent);
                        }

                        using (Stream src = entry.Open())
                        using (FileStream dst = new FileStream(outPath, FileMode.Create, FileAccess.Write, FileShare.None))
                        {
                            int n;
                            while ((n = src.Read(copyBuf, 0, copyBuf.Length)) > 0)
                            {
                                dst.Write(copyBuf, 0, n);
                            }
                        }

                        if (onProgress != null && (idx % 20 == 0 || idx == total))
                        {
                            int pct = (int)Math.Round(100.0 * idx / total);
                            onProgress(pct, "Unpacking standalone runtime (" + pct + "%)...");
                        }
                    }
                }
            }

            File.WriteAllText(readyMarker, DateTime.UtcNow.ToString("o"), Encoding.UTF8);
        }

        private static int LaunchExtractedApp(string cacheDir, string[] args, bool cliMode)
        {
            string pyExe = Path.Combine(cacheDir, cliMode ? @"runtime\python.exe" : @"runtime\pythonw.exe");
            string appPy = Path.Combine(cacheDir, @"app\app.py");

            StringBuilder argBuilder = new StringBuilder();
            argBuilder.Append("\"").Append(appPy).Append("\"");
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--reextract") continue;
                argBuilder.Append(" \"").Append(args[i].Replace("\"", "\\\"")).Append("\"");
            }

            ProcessStartInfo psi = new ProcessStartInfo(pyExe, argBuilder.ToString());
            psi.WorkingDirectory = Path.GetDirectoryName(appPy);
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;

            Process proc = Process.Start(psi);
            if (cliMode && proc != null)
            {
                proc.WaitForExit();
                return proc.ExitCode;
            }
            return 0;
        }
    }
}
