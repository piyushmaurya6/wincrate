using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("WinCrate")]
[assembly: AssemblyProduct("WinCrate — Windows Software Packager")]
[assembly: AssemblyVersion("1.0.0.0")]

namespace WinCrateLauncher
{
    internal static class Program
    {
        [STAThread]
        public static int Main(string[] args)
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string appPy = Path.Combine(baseDir, @"app\app.py");
            if (!File.Exists(appPy))
            {
                appPy = Path.Combine(baseDir, "app.py");
            }

            if (!File.Exists(appPy))
            {
                MessageBox.Show("Could not find WinCrate application files next to WinCrate.exe.", "WinCrate", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }

            bool cliMode = false;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--self-test" || args[i] == "--serve-only")
                {
                    cliMode = true;
                }
            }

            string pyExe = FindPythonExecutable(baseDir, cliMode);
            StringBuilder argBuilder = new StringBuilder();
            argBuilder.Append("\"").Append(appPy).Append("\"");
            for (int i = 0; i < args.Length; i++)
            {
                argBuilder.Append(" \"").Append(args[i].Replace("\"", "\\\"")).Append("\"");
            }

            ProcessStartInfo psi = new ProcessStartInfo(pyExe, argBuilder.ToString());
            psi.WorkingDirectory = Path.GetDirectoryName(appPy);
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;

            try
            {
                Process proc = Process.Start(psi);
                if (cliMode && proc != null)
                {
                    proc.WaitForExit();
                    return proc.ExitCode;
                }
                return 0;
            }
            catch (Exception ex)
            {
                MessageBox.Show("Failed to launch WinCrate runtime:\n" + ex.Message, "WinCrate", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }

        private static string FindPythonExecutable(string baseDir, bool cliMode)
        {
            string exeName = cliMode ? "python.exe" : "pythonw.exe";

            // 1. Prefer bundled standalone runtime next to WinCrate.exe (zero host Python required)
            string bundled = Path.Combine(baseDir, Path.Combine("runtime", exeName));
            if (File.Exists(bundled)) return bundled;

            string bundledDirect = Path.Combine(baseDir, exeName);
            if (File.Exists(bundledDirect)) return bundledDirect;

            // 2. Developer fallback: installed Python 3.x under LocalAppData
            string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string pyRoot = Path.Combine(localApp, @"Programs\Python");
            if (Directory.Exists(pyRoot))
            {
                string[] dirs = Directory.GetDirectories(pyRoot, "Python3*");
                Array.Sort(dirs);
                for (int i = dirs.Length - 1; i >= 0; i--)
                {
                    string candidate = Path.Combine(dirs[i], exeName);
                    if (File.Exists(candidate)) return candidate;
                }
            }
            return exeName;
        }
    }
}
