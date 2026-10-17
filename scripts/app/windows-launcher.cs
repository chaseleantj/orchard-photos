// Orchard.exe: start Orchard with the Python next to it, and say why if it stops without opening.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

static class Launcher
{
    const int TailLines = 15;

    static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string log = Path.Combine(Path.GetTempPath(), "Orchard.log");
        string python = Path.Combine(root, "runtime", "python.exe");
        if (!File.Exists(python))
        {
            // Opened from inside the zip, Explorer runs this program alone from a temporary folder.
            MessageBox.Show("Extract the whole Orchard folder from the zip first, then open Orchard.exe in it.", "Orchard", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        var start = new ProcessStartInfo(python, "-I -B -X utf8 -m server.api --window " + Arguments())
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        var tail = new Queue<string>();
        int status;
        // Shared, since a second launch writes here too, while it hands its folder to the first and quits.
        using (var writer = new StreamWriter(new FileStream(log, FileMode.Create, FileAccess.Write, FileShare.ReadWrite)))
        using (var server = new Process { StartInfo = start })
        {
            writer.AutoFlush = true;
            DataReceivedEventHandler write = (sender, line) =>
            {
                if (line.Data == null) return;
                lock (writer)
                {
                    writer.WriteLine(line.Data);
                    tail.Enqueue(line.Data);
                    if (tail.Count > TailLines) tail.Dequeue();
                }
            };
            server.OutputDataReceived += write;
            server.ErrorDataReceived += write;
            server.Start();
            server.BeginOutputReadLine();
            server.BeginErrorReadLine();
            server.WaitForExit();
            status = server.ExitCode;
        }
        // A service, like a CI runner, has no one to close the message.
        if (status != 0 && Environment.UserInteractive)
        {
            string message = "The end of its log, " + log + ":" + Environment.NewLine + Environment.NewLine + string.Join(Environment.NewLine, tail);
            MessageBox.Show(message, "Orchard stopped", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        return status;
    }

    // This program's own command line after its name, passed on to Python as it was typed.
    static string Arguments()
    {
        string line = Environment.CommandLine.TrimStart();
        int end = line.StartsWith("\"") ? line.IndexOf('"', 1) + 1 : line.IndexOf(' ');
        return end <= 0 || end >= line.Length ? "" : line.Substring(end).TrimStart();
    }
}
