const express = require('express');
const path = require('path');
const fs = require('fs');
const multer = require('multer');
const crypto = require('crypto');
const sharp = require('sharp');

const app = express();
const PORT = process.env.PORT || 3000;

// ── Directories & Files ──
const UPLOADS_DIR = path.join(__dirname, 'uploads');
const DATA_DIR = path.join(__dirname, 'data');
const VAULT_FILE = path.join(DATA_DIR, 'vault.json');
const PHOTO_REGISTRY_FILE = path.join(DATA_DIR, 'photo_registry.json');

// Ensure directories exist
[UPLOADS_DIR, DATA_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// Initialize data files if they don't exist
if (!fs.existsSync(VAULT_FILE)) {
  fs.writeFileSync(VAULT_FILE, JSON.stringify({ memories: [] }, null, 2));
}
if (!fs.existsSync(PHOTO_REGISTRY_FILE)) {
  fs.writeFileSync(PHOTO_REGISTRY_FILE, JSON.stringify({
    _description: "Photo Registry — Hash Map of all photos stored in the Memory Vault. Each key is a SHA-256 hash of the photo's pixel data. Use the key to look up any photo.",
    _format: {
      key: "SHA-256 hash (hex)",
      value: {
        filename: "Stored JPEG filename on disk (in /uploads)",
        originalName: "Original filename from the user's device",
        path: "Relative URL path to access the photo",
        width: "Image width in pixels",
        height: "Image height in pixels",
        sizeBytes: "File size in bytes",
        memoryId: "ID of the memory this photo belongs to (set after memory is saved)",
        memoryName: "Name of the item this photo belongs to (set after memory is saved)",
        uploadedAt: "ISO 8601 timestamp"
      }
    },
    photos: {}
  }, null, 2));
}

// ── Helpers: read/write JSON files ──
function readJSON(filepath) {
  try {
    return JSON.parse(fs.readFileSync(filepath, 'utf-8'));
  } catch {
    return null;
  }
}

function writeJSON(filepath, data) {
  fs.writeFileSync(filepath, JSON.stringify(data, null, 2));
}

function readVault() {
  return readJSON(VAULT_FILE) || { memories: [] };
}

function readPhotoRegistry() {
  return readJSON(PHOTO_REGISTRY_FILE) || { photos: {} };
}

// ── Multer config — upload to temp first, then process ──
const tempUpload = multer({
  dest: path.join(UPLOADS_DIR, '.temp'),
  limits: { fileSize: 100 * 1024 * 1024 }, // 100 MB
});

function guessExtension(mime) {
  const map = {
    'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/heic': '.heic',
    'audio/mp4': '.m4a', 'audio/aac': '.aac', 'audio/webm': '.webm',
    'audio/ogg': '.ogg', 'audio/mpeg': '.mp3', 'audio/wav': '.wav',
  };
  return map[mime] || '.bin';
}

// ── Middleware ──
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true, limit: '50mb' }));

// Serve static front-end
app.use(express.static(path.join(__dirname, 'public')));

// Serve uploaded files
app.use('/uploads', express.static(UPLOADS_DIR));

// ──────────────── API Routes ────────────────

// POST /api/upload — upload a single file (photo or voice)
app.post('/api/upload', tempUpload.single('file'), async (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: 'No file uploaded' });
  }

  const fileType = req.body.type || 'unknown';
  const tempPath = req.file.path;

  try {
    if (fileType === 'photo') {
      // ── PHOTO: convert to JPEG, hash, and save ──
      const imageBuffer = fs.readFileSync(tempPath);

      // Convert to JPEG using sharp (handles PNG, WebP, HEIC, etc.)
      const jpegBuffer = await sharp(imageBuffer)
        .jpeg({ quality: 92 })
        .toBuffer();

      // Get image metadata for dimensions
      const metadata = await sharp(jpegBuffer).metadata();

      // Generate SHA-256 hash of the JPEG pixel data
      const hashKey = crypto.createHash('sha256').update(jpegBuffer).digest('hex');

      // Save as <hash>.jpg
      const jpegFilename = `${hashKey}.jpg`;
      const jpegPath = path.join(UPLOADS_DIR, jpegFilename);
      fs.writeFileSync(jpegPath, jpegBuffer);

      // Remove temp file
      fs.unlinkSync(tempPath);

      // Register in photo registry
      const registry = readPhotoRegistry();
      registry.photos[hashKey] = {
        filename: jpegFilename,
        originalName: req.file.originalname,
        path: `/uploads/${jpegFilename}`,
        width: metadata.width,
        height: metadata.height,
        sizeBytes: jpegBuffer.length,
        memoryId: null,   // Will be linked when the memory is saved
        memoryName: null,
        uploadedAt: new Date().toISOString(),
      };
      writeJSON(PHOTO_REGISTRY_FILE, registry);

      console.log(`  📸 Photo saved: ${req.file.originalname} → ${jpegFilename}`);
      console.log(`     Key: ${hashKey}`);
      console.log(`     Size: ${metadata.width}x${metadata.height}, ${(jpegBuffer.length / 1024).toFixed(1)} KB`);

      return res.status(201).json({
        filename: jpegFilename,
        originalName: req.file.originalname,
        url: `/uploads/${jpegFilename}`,
        size: jpegBuffer.length,
        mimetype: 'image/jpeg',
        type: 'photo',
        hashKey,
        width: metadata.width,
        height: metadata.height,
      });

    } else {
      // ── VOICE NOTE: save as-is with a random ID ──
      const id = crypto.randomBytes(8).toString('hex');
      const ext = path.extname(req.file.originalname) || guessExtension(req.file.mimetype);
      const filename = `${id}${ext}`;
      const destPath = path.join(UPLOADS_DIR, filename);

      fs.renameSync(tempPath, destPath);
      const stat = fs.statSync(destPath);

      console.log(`  🎙️  Voice saved: ${req.file.originalname} → ${filename} (${(stat.size / 1024).toFixed(1)} KB)`);

      return res.status(201).json({
        filename,
        originalName: req.file.originalname,
        url: `/uploads/${filename}`,
        size: stat.size,
        mimetype: req.file.mimetype,
        type: 'voice',
      });
    }

  } catch (err) {
    // Clean up temp file on error
    if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath);
    console.error('Upload processing error:', err);
    return res.status(500).json({ error: 'Failed to process upload' });
  }
});

// POST /api/memories — save a new memory
app.post('/api/memories', (req, res) => {
  const { name, story, media } = req.body;

  if (!name || !media || !media.length) {
    return res.status(400).json({ error: 'Name and at least one media item required' });
  }

  const vault = readVault();

  const memoryId = crypto.randomBytes(6).toString('hex');
  const memory = {
    id: memoryId,
    name,
    story: story || '',
    media,
    date: new Date().toISOString(),
  };

  vault.memories.push(memory);
  writeJSON(VAULT_FILE, vault);

  // Link photos to this memory in the registry
  const registry = readPhotoRegistry();
  let linkedCount = 0;
  media.forEach(m => {
    if (m.type === 'photo' && m.hashKey && registry.photos[m.hashKey]) {
      registry.photos[m.hashKey].memoryId = memoryId;
      registry.photos[m.hashKey].memoryName = name;
      linkedCount++;
    }
  });
  if (linkedCount > 0) {
    writeJSON(PHOTO_REGISTRY_FILE, registry);
  }

  console.log(`  💾 Saved memory: "${name}" (${media.length} media files, ${linkedCount} photos linked)`);
  res.status(201).json(memory);
});

// GET /api/memories — list all memories
app.get('/api/memories', (req, res) => {
  const vault = readVault();
  res.json(vault);
});

// GET /api/memories/:id — get a single memory
app.get('/api/memories/:id', (req, res) => {
  const vault = readVault();
  const memory = vault.memories.find(m => m.id === req.params.id);
  if (!memory) return res.status(404).json({ error: 'Memory not found' });
  res.json(memory);
});

// GET /api/photos — get the full photo registry (developer endpoint)
app.get('/api/photos', (req, res) => {
  const registry = readPhotoRegistry();
  res.json(registry);
});

// GET /api/photos/:hashKey — look up a single photo by its hash key
app.get('/api/photos/:hashKey', (req, res) => {
  const registry = readPhotoRegistry();
  const photo = registry.photos[req.params.hashKey];
  if (!photo) return res.status(404).json({ error: 'Photo not found' });
  res.json({ key: req.params.hashKey, ...photo });
});

// DELETE /api/memories/:id — delete a memory and its files
app.delete('/api/memories/:id', (req, res) => {
  const vault = readVault();
  const idx = vault.memories.findIndex(m => m.id === req.params.id);
  if (idx === -1) return res.status(404).json({ error: 'Memory not found' });

  const memory = vault.memories[idx];
  const registry = readPhotoRegistry();

  // Delete associated files from disk & remove from registry
  memory.media.forEach(m => {
    const filePath = path.join(UPLOADS_DIR, m.filename);
    if (fs.existsSync(filePath)) {
      fs.unlinkSync(filePath);
      console.log(`  🗑️  Deleted file: ${m.filename}`);
    }
    // Remove from photo registry
    if (m.type === 'photo' && m.hashKey && registry.photos[m.hashKey]) {
      delete registry.photos[m.hashKey];
    }
  });

  writeJSON(PHOTO_REGISTRY_FILE, registry);

  vault.memories.splice(idx, 1);
  writeJSON(VAULT_FILE, vault);

  console.log(`  🗑️  Deleted memory: "${memory.name}"`);
  res.json({ message: 'Memory deleted', id: req.params.id });
});

// ── SPA fallback ──
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// ── Start ──
app.listen(PORT, '0.0.0.0', () => {
  console.log(`\n  🗃️  Memory Vault is running!\n`);
  console.log(`  ➜  Local:   http://localhost:${PORT}`);

  const nets = require('os').networkInterfaces();
  for (const name of Object.keys(nets)) {
    for (const net of nets[name]) {
      if (net.family === 'IPv4' && !net.internal) {
        console.log(`  ➜  Network: http://${net.address}:${PORT}  (open this on your phone!)`);
      }
    }
  }

  console.log(`\n  📁 Uploads:       ${UPLOADS_DIR}`);
  console.log(`  📄 Vault DB:      ${VAULT_FILE}`);
  console.log(`  🔑 Photo Registry: ${PHOTO_REGISTRY_FILE}\n`);
});
