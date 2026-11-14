using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("WinCrate Application Uninstaller")]
[assembly: AssemblyVersion("1.0.0.0")]

namespace WinCrateUninstall
{
    internal static class Program
    {
        [STAThread]
        public static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            bool silent = false;
            if (args != null)
            {
                foreach (string a in args)
                {
                    if (string.Equals(a, "--silent", StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(a, "/S", StringComparison.OrdinalIgnoreCase))
                        silent = true;
                }
            }

            string selfPath = Application.ExecutablePath;
            string installDir = Path.GetDirectoryName(selfPath);
            string receiptPath = Path.Combine(installDir, "wincrate_receipt.json");

            string appName = Path.GetFileName(installDir);
            string uninstRegKey = "";
            List<string> shortcuts = new List<string>();

            if (File.Exists(receiptPath))
            {
                try
                {
                    JavaScriptSerializer ser = new JavaScriptSerializer();
                    Dictionary<string, object> d = ser.Deserialize<Dictionary<string, object>>(File.ReadAllText(receiptPath, Encoding.UTF8));
                    if (d != null)
                    {
                        if (d.ContainsKey("appName") && d["appName"] != null) appName = d["appName"].ToString();
                        if (d.ContainsKey("uninstallRegKey") && d["uninstallRegKey"] != null) uninstRegKey = d["uninstallRegKey"].ToString();
                        if (d.ContainsKey("shortcuts") && d["shortcuts"] is ArrayList)
                        {
                            foreach (object s in (ArrayList)d["shortcuts"])
                            {
                                if (s != null) shortcuts.Add(s.ToString());
                            }
                        }
                    }
                }
                catch { }
            }

            if (!silent)
            {
                DialogResult res = MessageBox.Show(
                    "Remove " + appName + " and its shortcuts from this computer?",
                    "Uninstall " + appName,
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question);
                if (res != DialogResult.Yes) return 0;
            }

            foreach (string lnk in shortcuts)
            {
                try { if (File.Exists(lnk)) File.Delete(lnk); } catch { }
            }

            if (!string.IsNullOrEmpty(uninstRegKey))
            {
                try { Registry.CurrentUser.DeleteSubKeyTree(uninstRegKey, false); } catch { }
            }

            // Schedule self-removal of installDir after process exits
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo("cmd.exe", "/C ping 127.0.0.1 -n 2 > nul & rmdir /S /Q \"" + installDir + "\"");
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                Process.Start(psi);
            }
            catch { }

            if (!silent)
            {
                MessageBox.Show(appName + " has been uninstalled.", "Uninstall Complete", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            return 0;
        }
    }
}
