const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");

let crcTable = null;
function crc32(buffer) {
  if (!crcTable) {
    crcTable = Array.from({ length: 256 }, (_, value) => {
      let current = value;
      for (let bit = 0; bit < 8; bit += 1) current = (current & 1) ? 0xedb88320 ^ (current >>> 1) : current >>> 1;
      return current >>> 0;
    });
  }
  let crc = 0xffffffff;
  for (const byte of buffer) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data = Buffer.alloc(0)) {
  const name = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4); length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4); checksum.writeUInt32BE(crc32(Buffer.concat([name, data])));
  return Buffer.concat([length, name, data, checksum]);
}

function encodePng(width, height, rgba) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4);
  header[8] = 8; header[9] = 6;
  const rows = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y += 1) rgba.copy(rows, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", header), pngChunk("IDAT", zlib.deflateSync(rows)), pngChunk("IEND")
  ]);
}

function decodeTga(buffer) {
  const idLength = buffer[0];
  const imageType = buffer[2];
  const width = buffer.readUInt16LE(12); const height = buffer.readUInt16LE(14);
  const bits = buffer[16]; const bytesPerPixel = bits / 8;
  if (![2, 10].includes(imageType) || ![3, 4].includes(bytesPerPixel) || !width || !height) throw new Error("Nicht unterstuetztes TGA-Format");
  const pixels = Buffer.alloc(width * height * 4);
  const topOrigin = Boolean(buffer[17] & 0x20);
  let offset = 18 + idLength; let pixel = 0;
  const writePixel = (sourceOffset) => {
    const x = pixel % width; const sourceY = Math.floor(pixel / width); const y = topOrigin ? sourceY : height - 1 - sourceY;
    const target = (y * width + x) * 4;
    pixels[target] = buffer[sourceOffset + 2]; pixels[target + 1] = buffer[sourceOffset + 1]; pixels[target + 2] = buffer[sourceOffset];
    pixels[target + 3] = bytesPerPixel === 4 ? buffer[sourceOffset + 3] : 255; pixel += 1;
  };
  if (imageType === 2) while (pixel < width * height) { writePixel(offset); offset += bytesPerPixel; }
  else {
    while (pixel < width * height) {
      const packet = buffer[offset++]; const count = (packet & 0x7f) + 1;
      if (packet & 0x80) { for (let index = 0; index < count; index += 1) writePixel(offset); offset += bytesPerPixel; }
      else for (let index = 0; index < count; index += 1) { writePixel(offset); offset += bytesPerPixel; }
    }
  }
  return { width, height, pixels };
}

function color565(value) {
  return [Math.round(((value >> 11) & 31) * 255 / 31), Math.round(((value >> 5) & 63) * 255 / 63), Math.round((value & 31) * 255 / 31), 255];
}

function dxtColors(block, allowTransparent) {
  const first = block.readUInt16LE(0); const second = block.readUInt16LE(2);
  const a = color565(first); const b = color565(second);
  if (first > second || !allowTransparent) {
    return [a, b,
      a.map((value, i) => i === 3 ? 255 : Math.round((2 * value + b[i]) / 3)),
      a.map((value, i) => i === 3 ? 255 : Math.round((value + 2 * b[i]) / 3))];
  }
  return [a, b, a.map((value, i) => i === 3 ? 255 : Math.round((value + b[i]) / 2)), [0, 0, 0, 0]];
}

function alphaDxt5(block) {
  const values = [block[0], block[1]];
  if (values[0] > values[1]) for (let i = 1; i <= 6; i += 1) values.push(Math.round(((7 - i) * values[0] + i * values[1]) / 7));
  else {
    for (let i = 1; i <= 4; i += 1) values.push(Math.round(((5 - i) * values[0] + i * values[1]) / 5));
    values.push(0, 255);
  }
  let bits = 0n;
  for (let i = 0; i < 6; i += 1) bits |= BigInt(block[2 + i]) << BigInt(i * 8);
  return Array.from({ length: 16 }, (_, i) => values[Number((bits >> BigInt(i * 3)) & 7n)]);
}

function decodeDds(buffer) {
  if (buffer.toString("ascii", 0, 4) !== "DDS ") throw new Error("Ungueltige DDS-Datei");
  const height = buffer.readUInt32LE(12); const width = buffer.readUInt32LE(16);
  const fourCC = buffer.toString("ascii", 84, 88);
  if (!width || !height || !["DXT1", "DXT3", "DXT5"].includes(fourCC)) throw new Error(`Nicht unterstuetztes DDS-Format: ${fourCC}`);
  const pixels = Buffer.alloc(width * height * 4);
  const blockSize = fourCC === "DXT1" ? 8 : 16;
  let offset = 128;
  for (let by = 0; by < Math.ceil(height / 4); by += 1) {
    for (let bx = 0; bx < Math.ceil(width / 4); bx += 1) {
      const block = buffer.subarray(offset, offset + blockSize); offset += blockSize;
      const colorOffset = fourCC === "DXT1" ? 0 : 8;
      const colors = dxtColors(block.subarray(colorOffset), fourCC === "DXT1");
      const indices = block.readUInt32LE(colorOffset + 4);
      let alphas = Array(16).fill(255);
      if (fourCC === "DXT3") alphas = Array.from({ length: 16 }, (_, i) => ((block[Math.floor(i / 2)] >> ((i % 2) * 4)) & 15) * 17);
      if (fourCC === "DXT5") alphas = alphaDxt5(block);
      for (let i = 0; i < 16; i += 1) {
        const x = bx * 4 + i % 4; const y = by * 4 + Math.floor(i / 4);
        if (x >= width || y >= height) continue;
        const color = colors[(indices >>> (i * 2)) & 3]; const target = (y * width + x) * 4;
        pixels[target] = color[0]; pixels[target + 1] = color[1]; pixels[target + 2] = color[2]; pixels[target + 3] = Math.min(color[3], alphas[i]);
      }
    }
  }
  return { width, height, pixels };
}

function previewBytes(filePath) {
  const suffix = path.extname(filePath).toLowerCase();
  if (suffix === ".tga") { const image = decodeTga(fs.readFileSync(filePath)); return { body: encodePng(image.width, image.height, image.pixels), type: "image/png" }; }
  if (suffix === ".dds") { const image = decodeDds(fs.readFileSync(filePath)); return { body: encodePng(image.width, image.height, image.pixels), type: "image/png" }; }
  return null;
}

module.exports = { decodeDds, decodeTga, encodePng, previewBytes };
