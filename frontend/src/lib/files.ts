// Downloads and images from the API. In a browser these are plain links and <img> tags (the cookie rides along).
// In the Android app the page is not on the server's origin and the session is a bearer token, so the file is
// fetched with it and handed to the phone's share sheet (save, open with, send) instead.
import type { MouseEvent } from "react";
import { useEffect, useState } from "react";
import { Directory, Filesystem } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";
import { toast } from "sonner";
import { apiFetch } from "./api";
import { isNative } from "./native";

function fileNameFrom(res: Response, path: string, given?: string): string {
  if (given) return given;
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  if (m) {
    try {
      return decodeURIComponent(m[1]);
    } catch {
      return m[1];
    }
  }
  const last = path.split("?")[0].split("/").filter(Boolean).pop() ?? "vidhi-file";
  return last;
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.readAsDataURL(blob);
  });
}

async function shareApiFile(path: string, filename?: string): Promise<void> {
  const res = await apiFetch(path);
  if (!res.ok) throw new Error(String(res.status));
  const name = fileNameFrom(res, path, filename).replace(/[\\/:*?"<>|]/g, "_");
  const saved = await Filesystem.writeFile({ path: name, data: await toBase64(await res.blob()), directory: Directory.Cache });
  await Share.share({ title: name, url: saved.uri });
}

function fail() {
  toast.error("That file could not be opened. Check your connection and try again.");
}

/** Open or download a file from an /api path. Browsers: a new tab, as before. Android app: the share sheet. */
export function openApiFile(path: string, filename?: string): void {
  if (!isNative()) {
    window.open(path, "_blank");
    return;
  }
  void shareApiFile(path, filename).catch(fail);
}

/** Props for an <a> that points at an /api file. Browsers: unchanged link. Android app: fetch with the session, then share. */
export function fileLinkProps(path: string, options: { filename?: string; download?: boolean } = {}) {
  const { filename, download = true } = options;
  if (!isNative()) return download ? { href: path, download: true } : { href: path };
  return {
    href: "#",
    onClick: (e: MouseEvent) => {
      e.preventDefault();
      void shareApiFile(path, filename).catch(fail);
    },
  };
}

/** The src for an image served by the API. Browsers: the path itself. Android app: a blob fetched with the session. */
export function useApiImage(path: string | null): string | null {
  const [blobSrc, setBlobSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!path || !isNative()) return;
    let dead = false;
    let url: string | undefined;
    apiFetch(path)
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (b && !dead) {
          url = URL.createObjectURL(b);
          setBlobSrc(url);
        }
      })
      .catch(() => undefined);
    return () => {
      dead = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [path]);
  if (!path) return null;
  return isNative() ? blobSrc : path;
}
