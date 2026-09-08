import express, { Request, Response, NextFunction } from "express";
import cors from "cors";
import multer from "multer";
import path from "path";
import fs from "fs";
import { execFile } from "child_process";
import { promisify } from "util";
import crypto from "crypto";
import { PDFDocument, StandardFonts, rgb, degrees } from "pdf-lib";
import JSZip from "jszip";

const execFileAsync = promisify(execFile);

const app = express();
const PORT = 3000;
const FRONTEND_DIR = path.resolve(process.cwd(), "frontend");
const TEMP_DIR = path.resolve(process.cwd(), "temp");

if (!fs.existsSync(TEMP_DIR)) {
  fs.mkdirSync(TEMP_DIR, { recursive: true });
}

// Memory storage for uploads up to 100 MB
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 100 * 1024 * 1024 },
});

// Middleware
app.use(
  cors({
    origin: "*",
    methods: ["GET", "POST", "OPTIONS"],
    allowedHeaders: ["*"],
    exposedHeaders: [
      "X-Original-Size",
      "X-Compressed-Size",
      "X-Reduction-Percent",
      "Content-Disposition",
    ],
    maxAge: 600,
  })
);

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Security & caching headers middleware
app.use((req: Request, res: Response, next: NextFunction) => {
  const reqPath = req.path || "";
  if (
    reqPath.includes("..") ||
    reqPath.includes("\0") ||
    reqPath.toLowerCase().includes("%00") ||
    reqPath.toLowerCase().includes("%2e%2e")
  ) {
    return res.status(400).json({ detail: "Invalid request path." });
  }

  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  res.setHeader(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=()"
  );

  if (reqPath.startsWith("/api/")) {
    res.setHeader("Cache-Control", "no-store");
  }

  next();
});

// Helper: safe filename stem
function getStem(filename: string): string {
  const parsed = path.parse(filename || "document");
  return parsed.name.replace(/[^a-zA-Z0-9_\-\.]/g, "_") || "document";
}

// Helper: parse page ranges "1-3, 5, 8-10" to 0-based page indices
function parsePageRanges(rangesStr: string, totalPages: number): number[] {
  const pages = new Set<number>();
  for (const part of rangesStr.replace(/\s+/g, "").split(",")) {
    if (!part) continue;
    if (part.includes("-")) {
      const [a, b] = part.split("-");
      let start = parseInt(a, 10);
      let end = parseInt(b, 10);
      if (isNaN(start) || isNaN(end)) continue;
      if (start > end) [start, end] = [end, start];
      for (let i = start; i <= end; i++) {
        if (i >= 1 && i <= totalPages) {
          pages.add(i - 1);
        }
      }
    } else {
      const i = parseInt(part, 10);
      if (!isNaN(i) && i >= 1 && i <= totalPages) {
        pages.add(i - 1);
      }
    }
  }
  return Array.from(pages).sort((a, b) => a - b);
}

// ==========================================
// API ROUTES
// ==========================================

// 1. Health check
app.get("/api/health", (_req: Request, res: Response) => {
  res.json({
    status: "ok",
    service: "MJPDF",
    version: "1.1.1",
    ghostscript: true,
  });
});

// 2. Merge PDF
app.post(
  "/api/merge-pdf",
  upload.array("files", 50),
  async (req: Request, res: Response) => {
    const files = req.files as Express.Multer.File[];
    if (!files || files.length < 2) {
      return res.status(400).json({ detail: "At least 2 PDF files required" });
    }

    try {
      const mergedPdf = await PDFDocument.create();
      for (const f of files) {
        const doc = await PDFDocument.load(f.buffer, {
          ignoreEncryption: true,
        });
        const copied = await mergedPdf.copyPages(doc, doc.getPageIndices());
        copied.forEach((p) => mergedPdf.addPage(p));
      }

      const pdfBytes = await mergedPdf.save();
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader(
        "Content-Disposition",
        'attachment; filename="merged.pdf"'
      );
      return res.send(Buffer.from(pdfBytes));
    } catch (err: any) {
      return res
        .status(500)
        .json({ detail: `Merge failed: ${err.message || String(err)}` });
    }
  }
);

// 3. Split PDF (every page as separate PDF in a ZIP)
app.post(
  "/api/split-pdf",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    if (!file) {
      return res.status(400).json({ detail: "PDF file is required" });
    }

    try {
      const doc = await PDFDocument.load(file.buffer, {
        ignoreEncryption: true,
      });
      const total = doc.getPageCount();
      if (total === 0) {
        return res.status(400).json({ detail: "PDF has no pages" });
      }

      const zip = new JSZip();
      for (let i = 0; i < total; i++) {
        const singleDoc = await PDFDocument.create();
        const [copied] = await singleDoc.copyPages(doc, [i]);
        singleDoc.addPage(copied);
        const bytes = await singleDoc.save();
        zip.file(`page_${i + 1}.pdf`, bytes);
      }

      const zipBuffer = await zip.generateAsync({
        type: "nodebuffer",
        compression: "DEFLATE",
      });
      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/zip");
      res.setHeader(
        "Content-Disposition",
        `attachment; filename="${stem}_pages.zip"`
      );
      return res.send(zipBuffer);
    } catch (err: any) {
      return res
        .status(500)
        .json({ detail: `Split failed: ${err.message || String(err)}` });
    }
  }
);

// 4. Extract pages
app.post(
  "/api/extract-pages",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    const pagesStr = (req.body.pages || "").trim();
    if (!file) {
      return res.status(400).json({ detail: "PDF file is required" });
    }
    if (!pagesStr) {
      return res
        .status(400)
        .json({ detail: "Pages to extract are required (e.g. 1-3, 5)" });
    }

    try {
      const doc = await PDFDocument.load(file.buffer, {
        ignoreEncryption: true,
      });
      const total = doc.getPageCount();
      const indices = parsePageRanges(pagesStr, total);
      if (indices.length === 0) {
        return res
          .status(400)
          .json({ detail: "No valid pages match the requested range" });
      }

      const extractedDoc = await PDFDocument.create();
      const copied = await extractedDoc.copyPages(doc, indices);
      copied.forEach((p) => extractedDoc.addPage(p));

      const pdfBytes = await extractedDoc.save();
      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader(
        "Content-Disposition",
        `attachment; filename="${stem}_extracted.pdf"`
      );
      return res.send(Buffer.from(pdfBytes));
    } catch (err: any) {
      return res
        .status(400)
        .json({ detail: `Extraction failed: ${err.message || String(err)}` });
    }
  }
);

// 5. Delete pages
app.post(
  "/api/delete-pages",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    const pagesStr = (req.body.pages || "").trim();
    if (!file) {
      return res.status(400).json({ detail: "PDF file is required" });
    }
    if (!pagesStr) {
      return res
        .status(400)
        .json({ detail: "Pages to delete are required (e.g. 2, 5, 7-9)" });
    }

    try {
      const doc = await PDFDocument.load(file.buffer, {
        ignoreEncryption: true,
      });
      const total = doc.getPageCount();
      const toDelete = new Set(parsePageRanges(pagesStr, total));
      const keepIndices = [];
      for (let i = 0; i < total; i++) {
        if (!toDelete.has(i)) {
          keepIndices.push(i);
        }
      }

      if (keepIndices.length === 0) {
        return res
          .status(400)
          .json({ detail: "Cannot delete all pages of the document" });
      }

      const newDoc = await PDFDocument.create();
      const copied = await newDoc.copyPages(doc, keepIndices);
      copied.forEach((p) => newDoc.addPage(p));

      const pdfBytes = await newDoc.save();
      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader(
        "Content-Disposition",
        `attachment; filename="${stem}_deleted.pdf"`
      );
      return res.send(Buffer.from(pdfBytes));
    } catch (err: any) {
      return res
        .status(400)
        .json({ detail: `Delete failed: ${err.message || String(err)}` });
    }
  }
);

// 6. Rotate PDF
app.post(
  "/api/rotate-pdf",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    const angle = parseInt(req.body.angle || "90", 10);
    const pagesStr = (req.body.pages || "").trim();
    if (!file) {
      return res.status(400).json({ detail: "PDF file is required" });
    }

    try {
      const doc = await PDFDocument.load(file.buffer, {
        ignoreEncryption: true,
      });
      const total = doc.getPageCount();
      const targetIndices = pagesStr
        ? parsePageRanges(pagesStr, total)
        : doc.getPageIndices();

      for (const idx of targetIndices) {
        const page = doc.getPage(idx);
        const currentRot = page.getRotation().angle;
        page.setRotation(degrees((currentRot + angle) % 360));
      }

      const pdfBytes = await doc.save();
      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader(
        "Content-Disposition",
        `attachment; filename="${stem}_rotated.pdf"`
      );
      return res.send(Buffer.from(pdfBytes));
    } catch (err: any) {
      return res
        .status(400)
        .json({ detail: `Rotate failed: ${err.message || String(err)}` });
    }
  }
);

// 7. Organize PDF (reorder pages)
app.post(
  "/api/organize-pdf",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    const pageOrderStr = (req.body.page_order || "").trim();
    if (!file) {
      return res.status(400).json({ detail: "PDF file is required" });
    }
    if (!pageOrderStr) {
      return res
        .status(400)
        .json({ detail: "Page order is required (e.g. 3,1,2,4)" });
    }

    try {
      const doc = await PDFDocument.load(file.buffer, {
        ignoreEncryption: true,
      });
      const total = doc.getPageCount();
      const order = pageOrderStr
        .split(",")
        .map((x) => parseInt(x.trim(), 10) - 1)
        .filter((x) => !isNaN(x) && x >= 0 && x < total);

      if (order.length === 0) {
        return res
          .status(400)
          .json({ detail: "Invalid page order specified" });
      }

      const organizedDoc = await PDFDocument.create();
      const copied = await organizedDoc.copyPages(doc, order);
      copied.forEach((p) => organizedDoc.addPage(p));

      const pdfBytes = await organizedDoc.save();
      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader(
        "Content-Disposition",
        `attachment; filename="${stem}_organized.pdf"`
      );
      return res.send(Buffer.from(pdfBytes));
    } catch (err: any) {
      return res
        .status(400)
        .json({ detail: `Organize failed: ${err.message || String(err)}` });
    }
  }
);

// 8. Images to PDF
app.post(
  "/api/images-to-pdf",
  upload.array("files", 50),
  async (req: Request, res: Response) => {
    const files = req.files as Express.Multer.File[];
    if (!files || files.length === 0) {
      return res.status(400).json({ detail: "At least one image is required" });
    }

    const pageSize = (req.body.page_size || "A4").toUpperCase();
    const orientation = (req.body.orientation || "portrait").toLowerCase();

    // 72 points per inch
    let [pw, ph] =
      pageSize === "LETTER" ? [612, 792] : [595.28, 841.89]; // A4 default
    if (orientation === "landscape") {
      [pw, ph] = [ph, pw];
    }

    try {
      const pdfDoc = await PDFDocument.create();
      const margin = 20;
      const maxW = pw - margin * 2;
      const maxH = ph - margin * 2;

      for (const f of files) {
        let embeddedImage;
        const isPng =
          f.buffer.length >= 8 &&
          f.buffer[0] === 0x89 &&
          f.buffer[1] === 0x50 &&
          f.buffer[2] === 0x4e &&
          f.buffer[3] === 0x47;

        try {
          if (isPng) {
            embeddedImage = await pdfDoc.embedPng(f.buffer);
          } else {
            embeddedImage = await pdfDoc.embedJpg(f.buffer);
          }
        } catch {
          // Fallback retry
          try {
            embeddedImage = isPng
              ? await pdfDoc.embedJpg(f.buffer)
              : await pdfDoc.embedPng(f.buffer);
          } catch {
            continue; // skip unparseable image
          }
        }

        const imgW = embeddedImage.width;
        const imgH = embeddedImage.height;
        const scale = Math.min(maxW / imgW, maxH / imgH, 1);
        const drawW = imgW * scale;
        const drawH = imgH * scale;
        const posX = margin + (maxW - drawW) / 2;
        const posY = margin + (maxH - drawH) / 2;

        const page = pdfDoc.addPage([pw, ph]);
        page.drawImage(embeddedImage, {
          x: posX,
          y: posY,
          width: drawW,
          height: drawH,
        });
      }

      if (pdfDoc.getPageCount() === 0) {
        return res
          .status(400)
          .json({ detail: "Could not embed any of the provided images" });
      }

      const pdfBytes = await pdfDoc.save();
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader(
        "Content-Disposition",
        'attachment; filename="images.pdf"'
      );
      return res.send(Buffer.from(pdfBytes));
    } catch (err: any) {
      return res.status(500).json({
        detail: `Image conversion failed: ${err.message || String(err)}`,
      });
    }
  }
);

// 9. Watermark PDF
app.post(
  "/api/watermark-pdf",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    const text = (req.body.text || "CONFIDENTIAL").trim();
    const opacity = Math.max(
      0.05,
      Math.min(1, parseFloat(req.body.opacity || "0.35"))
    );
    const rotation = parseFloat(req.body.rotation || "45");
    const fontSize = Math.max(
      10,
      Math.min(150, parseFloat(req.body.font_size || "40"))
    );

    if (!file) {
      return res.status(400).json({ detail: "PDF file is required" });
    }

    try {
      const doc = await PDFDocument.load(file.buffer, {
        ignoreEncryption: true,
      });
      const font = await doc.embedFont(StandardFonts.HelveticaBold);
      const total = doc.getPageCount();

      for (let i = 0; i < total; i++) {
        const page = doc.getPage(i);
        const { width, height } = page.getSize();
        const textWidth = font.widthOfTextAtSize(text, fontSize);
        const textHeight = font.heightAtSize(fontSize);

        // Center on the page
        const cx = width / 2;
        const cy = height / 2;

        page.drawText(text, {
          x: cx - textWidth / 2,
          y: cy - textHeight / 2,
          size: fontSize,
          font,
          color: rgb(0.5, 0.5, 0.5),
          opacity,
          rotate: degrees(rotation),
        });
      }

      const pdfBytes = await doc.save();
      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader(
        "Content-Disposition",
        `attachment; filename="${stem}_watermarked.pdf"`
      );
      return res.send(Buffer.from(pdfBytes));
    } catch (err: any) {
      return res
        .status(500)
        .json({ detail: `Watermark failed: ${err.message || String(err)}` });
    }
  }
);

// 10. Compress PDF (via Ghostscript)
app.post(
  "/api/compress-pdf",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    const level = (req.body.level || "medium").toLowerCase();
    if (!file) {
      return res.status(400).json({ detail: "PDF file is required" });
    }

    const settingsMap: Record<string, string> = {
      high: "/screen",
      medium: "/ebook",
      low: "/printer",
    };
    const gsSetting = settingsMap[level] || "/ebook";

    const jobId = crypto.randomUUID();
    const inPath = path.join(TEMP_DIR, `comp_in_${jobId}.pdf`);
    const outPath = path.join(TEMP_DIR, `comp_out_${jobId}.pdf`);

    try {
      await fs.promises.writeFile(inPath, file.buffer);
      const originalSize = file.buffer.length;

      await execFileAsync("gs", [
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        `-dPDFSETTINGS=${gsSetting}`,
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        `-sOutputFile=${outPath}`,
        inPath,
      ]);

      const stat = await fs.promises.stat(outPath);
      let finalBytes: Buffer;
      let compressedSize = stat.size;

      // If compression resulted in smaller file, use it; otherwise use original
      if (compressedSize < originalSize && compressedSize > 100) {
        finalBytes = await fs.promises.readFile(outPath);
      } else {
        finalBytes = file.buffer;
        compressedSize = originalSize;
      }

      const reduction = Math.max(
        0,
        Math.round(((originalSize - compressedSize) / originalSize) * 100)
      );

      const stem = getStem(file.originalname);
      res.setHeader("X-Original-Size", String(originalSize));
      res.setHeader("X-Compressed-Size", String(compressedSize));
      res.setHeader("X-Reduction-Percent", String(reduction));
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader(
        "Content-Disposition",
        `attachment; filename="${stem}_compressed.pdf"`
      );
      return res.send(finalBytes);
    } catch (err: any) {
      return res
        .status(500)
        .json({ detail: `Compression failed: ${err.message || String(err)}` });
    } finally {
      fs.promises.unlink(inPath).catch(() => {});
      fs.promises.unlink(outPath).catch(() => {});
    }
  }
);

// 11. PDF to Images (via Ghostscript)
app.post(
  "/api/pdf-to-images",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    const format = (req.body.format || "jpg").toLowerCase();
    const dpi = parseInt(req.body.dpi || "150", 10);
    const pagesStr = (req.body.pages || "").trim();

    if (!file) {
      return res.status(400).json({ detail: "PDF file is required" });
    }
    if (format !== "jpg" && format !== "png") {
      return res.status(400).json({ detail: "format must be jpg or png" });
    }

    const jobId = crypto.randomUUID();
    const jobDir = path.join(TEMP_DIR, `p2i_${jobId}`);
    const inPath = path.join(jobDir, "input.pdf");

    try {
      await fs.promises.mkdir(jobDir, { recursive: true });
      await fs.promises.writeFile(inPath, file.buffer);

      const gsDevice = format === "png" ? "png16m" : "jpeg";
      const outPattern = path.join(jobDir, `page_%d.${format}`);

      await execFileAsync("gs", [
        `-sDEVICE=${gsDevice}`,
        `-r${dpi}`,
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        `-sOutputFile=${outPattern}`,
        inPath,
      ]);

      const filesInDir = await fs.promises.readdir(jobDir);
      const imgFiles = filesInDir
        .filter((f) => f.startsWith("page_") && f.endsWith(`.${format}`))
        .sort((a, b) => {
          const numA = parseInt(a.replace(/\D/g, ""), 10);
          const numB = parseInt(b.replace(/\D/g, ""), 10);
          return numA - numB;
        });

      if (imgFiles.length === 0) {
        return res
          .status(500)
          .json({ detail: "Could not render pages into images" });
      }

      // Filter pages if specified
      let selectedImgs = imgFiles;
      if (pagesStr) {
        const allowedPageNumbers = new Set(
          parsePageRanges(pagesStr, imgFiles.length).map((i) => i + 1)
        );
        selectedImgs = imgFiles.filter((f) => {
          const pageNum = parseInt(f.replace(/\D/g, ""), 10);
          return allowedPageNumbers.has(pageNum);
        });
      }

      const zip = new JSZip();
      for (const imgName of selectedImgs) {
        const imgBuffer = await fs.promises.readFile(
          path.join(jobDir, imgName)
        );
        zip.file(imgName, imgBuffer);
      }

      const zipBuffer = await zip.generateAsync({
        type: "nodebuffer",
        compression: "DEFLATE",
      });
      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/zip");
      res.setHeader(
        "Content-Disposition",
        `attachment; filename="${stem}_images.zip"`
      );
      return res.send(zipBuffer);
    } catch (err: any) {
      return res.status(500).json({
        detail: `PDF to Images failed: ${err.message || String(err)}`,
      });
    } finally {
      fs.promises.rm(jobDir, { recursive: true, force: true }).catch(() => {});
    }
  }
);

// 12. Protect PDF (password encryption via Ghostscript)
app.post(
  "/api/protect-pdf",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    const password = (req.body.password || "").trim();
    if (!file) {
      return res.status(400).json({ detail: "PDF file is required" });
    }
    if (!password) {
      return res.status(400).json({ detail: "Password is required" });
    }

    const jobId = crypto.randomUUID();
    const inPath = path.join(TEMP_DIR, `prot_in_${jobId}.pdf`);
    const outPath = path.join(TEMP_DIR, `prot_out_${jobId}.pdf`);

    try {
      await fs.promises.writeFile(inPath, file.buffer);

      await execFileAsync("gs", [
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        `-sOwnerPassword=${password}`,
        `-sUserPassword=${password}`,
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        `-sOutputFile=${outPath}`,
        inPath,
      ]);

      const outBuffer = await fs.promises.readFile(outPath);
      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader(
        "Content-Disposition",
        `attachment; filename="${stem}_protected.pdf"`
      );
      return res.send(outBuffer);
    } catch (err: any) {
      return res
        .status(500)
        .json({ detail: `Protection failed: ${err.message || String(err)}` });
    } finally {
      fs.promises.unlink(inPath).catch(() => {});
      fs.promises.unlink(outPath).catch(() => {});
    }
  }
);

// 13. Unlock PDF (remove password via Ghostscript)
app.post(
  "/api/unlock-pdf",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    const password = (req.body.password || "").trim();
    if (!file) {
      return res.status(400).json({ detail: "PDF file is required" });
    }
    if (!password) {
      return res.status(400).json({ detail: "Password is required" });
    }

    const jobId = crypto.randomUUID();
    const inPath = path.join(TEMP_DIR, `unl_in_${jobId}.pdf`);
    const outPath = path.join(TEMP_DIR, `unl_out_${jobId}.pdf`);

    try {
      await fs.promises.writeFile(inPath, file.buffer);

      await execFileAsync("gs", [
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        `-sPDFPassword=${password}`,
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        `-sOutputFile=${outPath}`,
        inPath,
      ]);

      const outBuffer = await fs.promises.readFile(outPath);
      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader(
        "Content-Disposition",
        `attachment; filename="${stem}_unlocked.pdf"`
      );
      return res.send(outBuffer);
    } catch (err: any) {
      const msg = String(err.stderr || err.message || "");
      if (
        msg.toLowerCase().includes("password did not work") ||
        msg.toLowerCase().includes("invalidfileaccess") ||
        msg.toLowerCase().includes("cannot decrypt")
      ) {
        return res.status(403).json({
          detail: "Incorrect password or the file could not be unlocked.",
        });
      }
      return res
        .status(500)
        .json({ detail: `Unlock failed: ${err.message || String(err)}` });
    } finally {
      fs.promises.unlink(inPath).catch(() => {});
      fs.promises.unlink(outPath).catch(() => {});
    }
  }
);

async function prepareLibreOfficeProfile(profileDir: string): Promise<void> {
  const userDir = path.join(profileDir, "user");
  await fs.promises.mkdir(userDir, { recursive: true });
  const xcuContent = `<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <item oor:path="/org.openoffice.Office.Common/I18N/CTL"><prop oor:name="CTLFont" oor:op="fuse"><value>true</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/I18N/CTL"><prop oor:name="CTLSequenceChecking" oor:op="fuse"><value>true</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/I18N/CTL"><prop oor:name="CTLSequenceCheckingRestricted" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/I18N/CTL"><prop oor:name="CTLSequenceCheckingTypeAndReplace" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="UsePrinterMetrics" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="AddSpacing" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="AddSpacingAtPages" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="UseOurTabStopFormat" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="NoExternalLeading" oor:op="fuse"><value>true</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="UseLineSpacing" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="AddTableSpacing" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="AddTableLineSpacing" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="UseOurTextWrapping" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="ConsiderWrappingStyle" oor:op="fuse"><value>true</value></prop></item>
  <item oor:path="/org.openoffice.Office.Compatibility/AllFileFormats"><prop oor:name="ExpandWordSpace" oor:op="fuse"><value>true</value></prop></item>
  <item oor:path="/org.openoffice.Office.Writer/Layout/Other"><prop oor:name="UsePrinterMetrics" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Writer/Layout/Line"><prop oor:name="AddLeading" oor:op="fuse"><value>false</value></prop></item>
</oor:items>`;
  await fs.promises.writeFile(
    path.join(userDir, "registrymodifications.xcu"),
    xcuContent,
    "utf8"
  );
}

// 14. Word to PDF conversion (LibreOffice with exact Microsoft typography & alignment preservation)
app.post(
  "/api/word-to-pdf",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    if (!file) {
      return res
        .status(400)
        .json({ detail: "Word file (.doc or .docx) is required" });
    }

    const ext = path.extname(file.originalname || "").toLowerCase() || ".docx";
    const allowedExts = [".doc", ".docx", ".rtf", ".odt", ".txt"];
    const targetExt = allowedExts.includes(ext) ? ext : ".docx";

    const jobId = crypto.randomUUID();
    const jobDir = path.join(TEMP_DIR, `word_${jobId}`);
    const inPath = path.join(jobDir, `input${targetExt}`);
    const profileDir = path.join(TEMP_DIR, `lo_prof_${jobId}`);

    try {
      await fs.promises.mkdir(jobDir, { recursive: true });
      await fs.promises.writeFile(inPath, file.buffer);
      await prepareLibreOfficeProfile(profileDir);

      const filterOptions = JSON.stringify({
        EmbedStandardFonts: { type: "boolean", value: "true" },
        UseLosslessCompression: { type: "boolean", value: "true" },
        ReduceImageResolution: { type: "boolean", value: "false" },
        MaxImageResolution: { type: "long", value: "300" },
        SelectPdfVersion: { type: "long", value: "0" },
        ExportFormFields: { type: "boolean", value: "true" },
        ExportBookmarks: { type: "boolean", value: "true" },
        IsSkipEmptyPages: { type: "boolean", value: "false" },
      });

      await execFileAsync(
        "soffice",
        [
          `-env:UserInstallation=file://${profileDir}`,
          "--headless",
          "--invisible",
          "--nologo",
          "--nodefault",
          "--nofirststartwizard",
          "--norestore",
          "--convert-to",
          `pdf:writer_pdf_Export:${filterOptions}`,
          "--outdir",
          jobDir,
          inPath,
        ],
        {
          timeout: 60000,
          env: {
            ...process.env,
            SAL_USE_VCLPLUGIN: "svp",
          },
        }
      );

      const expectedOutPath = path.join(jobDir, "input.pdf");
      let pdfBytes: Buffer;
      if (fs.existsSync(expectedOutPath)) {
        pdfBytes = await fs.promises.readFile(expectedOutPath);
      } else {
        const files = await fs.promises.readdir(jobDir);
        const pdfFile = files.find((f) => f.endsWith(".pdf"));
        if (!pdfFile) {
          throw new Error("PDF file was not created by conversion engine.");
        }
        pdfBytes = await fs.promises.readFile(path.join(jobDir, pdfFile));
      }

      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader("Content-Disposition", `attachment; filename="${stem}.pdf"`);
      return res.send(pdfBytes);
    } catch (err: any) {
      console.error("Word to PDF conversion error:", err);
      return res.status(500).json({
        detail: `Word to PDF conversion failed: ${err.message || String(err)}`,
      });
    } finally {
      fs.promises.rm(jobDir, { recursive: true, force: true }).catch(() => {});
      fs.promises.rm(profileDir, { recursive: true, force: true }).catch(() => {});
    }
  }
);

// 15. PowerPoint to PDF conversion
app.post(
  "/api/pptx-to-pdf",
  upload.single("file"),
  async (req: Request, res: Response) => {
    const file = req.file;
    if (!file) {
      return res
        .status(400)
        .json({ detail: "PowerPoint file (.ppt or .pptx) is required" });
    }

    const ext = path.extname(file.originalname || "").toLowerCase() || ".pptx";
    const allowedExts = [".ppt", ".pptx", ".odp"];
    const targetExt = allowedExts.includes(ext) ? ext : ".pptx";

    const jobId = crypto.randomUUID();
    const jobDir = path.join(TEMP_DIR, `pptx_${jobId}`);
    const inPath = path.join(jobDir, `input${targetExt}`);
    const profileDir = path.join(TEMP_DIR, `lo_prof_${jobId}`);

    try {
      await fs.promises.mkdir(jobDir, { recursive: true });
      await fs.promises.writeFile(inPath, file.buffer);
      await prepareLibreOfficeProfile(profileDir);

      const filterOptions = JSON.stringify({
        EmbedStandardFonts: { type: "boolean", value: "true" },
        UseLosslessCompression: { type: "boolean", value: "true" },
        ReduceImageResolution: { type: "boolean", value: "false" },
        MaxImageResolution: { type: "long", value: "300" },
        SelectPdfVersion: { type: "long", value: "0" },
      });

      await execFileAsync(
        "soffice",
        [
          `-env:UserInstallation=file://${profileDir}`,
          "--headless",
          "--invisible",
          "--nologo",
          "--nodefault",
          "--nofirststartwizard",
          "--norestore",
          "--convert-to",
          `pdf:impress_pdf_Export:${filterOptions}`,
          "--outdir",
          jobDir,
          inPath,
        ],
        {
          timeout: 60000,
          env: {
            ...process.env,
            SAL_USE_VCLPLUGIN: "svp",
          },
        }
      );

      const expectedOutPath = path.join(jobDir, "input.pdf");
      let pdfBytes: Buffer;
      if (fs.existsSync(expectedOutPath)) {
        pdfBytes = await fs.promises.readFile(expectedOutPath);
      } else {
        const files = await fs.promises.readdir(jobDir);
        const pdfFile = files.find((f) => f.endsWith(".pdf"));
        if (!pdfFile) {
          throw new Error("PDF file was not created by conversion engine.");
        }
        pdfBytes = await fs.promises.readFile(path.join(jobDir, pdfFile));
      }

      const stem = getStem(file.originalname);
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader("Content-Disposition", `attachment; filename="${stem}.pdf"`);
      return res.send(pdfBytes);
    } catch (err: any) {
      console.error("PowerPoint to PDF conversion error:", err);
      return res.status(500).json({
        detail: `PowerPoint to PDF conversion failed: ${err.message || String(err)}`,
      });
    } finally {
      fs.promises.rm(jobDir, { recursive: true, force: true }).catch(() => {});
      fs.promises.rm(profileDir, { recursive: true, force: true }).catch(() => {});
    }
  }
);

// ==========================================
// STATIC FILES & SPA ROUTING
// ==========================================

const ALLOWED_STATIC_PAGES = new Set([
  "about.html",
  "contact.html",
  "download.html",
  "terms.html",
  "privacy.html",
  "privacy-policy.html",
  "cookie-policy.html",
  "404.html",
]);

const PRETTY_PATHS: Record<string, string> = {
  "privacy-policy": "privacy-policy.html",
  "cookie-policy": "cookie-policy.html",
  about: "about.html",
  contact: "contact.html",
  download: "download.html",
  terms: "terms.html",
  privacy: "privacy.html",
};

const ALLOWED_TOOL_IDS = new Set([
  "word-to-pdf",
  "pptx-to-pdf",
  "compress-pdf",
  "merge-pdf",
  "split-pdf",
  "extract-pages",
  "delete-pages",
  "images-to-pdf",
  "pdf-to-images",
  "rotate-pdf",
  "organize-pdf",
  "watermark-pdf",
  "protect-pdf",
  "unlock-pdf",
]);

// Static assets
app.use("/static", express.static(path.join(FRONTEND_DIR, "static")));

// Root route
app.get("/", (_req: Request, res: Response) => {
  res.sendFile(path.join(FRONTEND_DIR, "index.html"));
});

// Robots and Sitemap
app.get("/robots.txt", (_req: Request, res: Response) => {
  const file = path.join(FRONTEND_DIR, "robots.txt");
  if (fs.existsSync(file)) return res.sendFile(file);
  return res.status(404).send("Not found");
});

app.get("/sitemap.xml", (_req: Request, res: Response) => {
  const file = path.join(FRONTEND_DIR, "sitemap.xml");
  if (fs.existsSync(file)) return res.sendFile(file);
  return res.status(404).send("Not found");
});

app.get("/googleda3e7bc76d15fc35.html", (_req: Request, res: Response) => {
  const file = path.join(FRONTEND_DIR, "googleda3e7bc76d15fc35.html");
  if (fs.existsSync(file)) return res.sendFile(file);
  return res.status(404).send("Not found");
});

// Page and tool routes
app.get("/:page_name", (req: Request, res: Response) => {
  const pageName = req.params.page_name;

  if (pageName === "api") {
    return res.status(404).json({ detail: "Not found" });
  }

  // Pretty routes
  if (PRETTY_PATHS[pageName]) {
    const file = path.join(FRONTEND_DIR, PRETTY_PATHS[pageName]);
    if (fs.existsSync(file)) return res.sendFile(file);
  }

  // Allowed direct HTML files
  if (ALLOWED_STATIC_PAGES.has(pageName)) {
    const file = path.join(FRONTEND_DIR, pageName);
    if (fs.existsSync(file)) return res.sendFile(file);
  }

  // Allowed tool routes -> SPA index.html
  if (ALLOWED_TOOL_IDS.has(pageName)) {
    return res.sendFile(path.join(FRONTEND_DIR, "index.html"));
  }

  // 404
  const notFoundPage = path.join(FRONTEND_DIR, "404.html");
  if (fs.existsSync(notFoundPage)) {
    return res.status(404).sendFile(notFoundPage);
  }
  return res.status(404).send("404 — Page not found");
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`MJPDF server running on http://0.0.0.0:${PORT}`);
});
