// Loaded only for export by Windows PowerShell 5.1 / .NET Framework.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace RedmineReadonly
{
    public static class FinalDirectoryPath
    {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFileW(string name, uint access,
            uint share, IntPtr security, uint disposition, uint flags, IntPtr template);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint GetFinalPathNameByHandleW(SafeFileHandle handle,
            StringBuilder path, uint length, uint flags);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint GetFileAttributesW(string name);

        [StructLayout(LayoutKind.Sequential)]
        private struct FileInformation
        {
            public uint Attributes, CreationLow, CreationHigh, AccessLow, AccessHigh,
                WriteLow, WriteHigh, Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetFileInformationByHandle(SafeFileHandle handle,
            out FileInformation information);

        private static bool Missing(int error) { return error == 2 || error == 3; }
        private static IOException Unresolved() { return new IOException("output path validation failed"); }

        public static string Resolve(string path, bool allowMissing)
        {
            var suffix = new Stack<string>();
            while (true)
            {
                // Follow reparse points. No data access, creation or directory changes.
                using (SafeFileHandle handle = CreateFileW(path, 0, 7, IntPtr.Zero,
                    3, 0x02000000, IntPtr.Zero))
                {
                    if (!handle.IsInvalid)
                    {
                        FileInformation info;
                        if (!GetFileInformationByHandle(handle, out info) ||
                            (info.Attributes & 0x10) == 0) { throw Unresolved(); }
                        var buffer = new StringBuilder(512);
                        // FILE_NAME_NORMALIZED | VOLUME_NAME_NT avoids DOS drive aliases.
                        uint length = GetFinalPathNameByHandleW(handle, buffer, (uint)buffer.Capacity, 2);
                        if (length >= buffer.Capacity && length < 32768)
                        {
                            buffer = new StringBuilder((int)length + 1);
                            length = GetFinalPathNameByHandleW(handle, buffer, (uint)buffer.Capacity, 2);
                        }
                        if (length == 0 || length >= buffer.Capacity) { throw Unresolved(); }
                        string result = buffer.ToString();
                        if (!result.StartsWith(@"\Device\", StringComparison.OrdinalIgnoreCase))
                            { throw Unresolved(); }
                        foreach (string component in suffix)
                            { result = result.TrimEnd('\\') + @"\" + component; }
                        return result;
                    }
                    if (!allowMissing || !Missing(Marshal.GetLastWin32Error())) { throw Unresolved(); }
                }
                // A dangling link is not a missing directory. Walk upwards only
                // after both operations report absence, never on access/IO errors.
                uint attributes = GetFileAttributesW(path);
                int attributeError = Marshal.GetLastWin32Error();
                if (attributes != UInt32.MaxValue || !Missing(attributeError)) { throw Unresolved(); }
                string parent = Path.GetDirectoryName(path);
                string componentName = Path.GetFileName(path);
                if (String.IsNullOrEmpty(parent) || String.IsNullOrEmpty(componentName) ||
                    parent == path) { throw Unresolved(); }
                suffix.Push(componentName);
                path = parent;
            }
        }
    }
}
