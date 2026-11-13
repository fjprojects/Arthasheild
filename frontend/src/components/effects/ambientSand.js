/**
 * Ambient sand simulation.
 *
 * A pure, DOM-free model of the organic sand texture used by the
 * `AmbientBackground` component. Keeping it separate from the React layer
 * means the motion can be verified deterministically (and its cost measured)
 * without a browser or a rendering pipeline.
 *
 * Model
 * -----
 * The texture is built from two layers that share one noise field, so the
 * grain always lies inside the shapes it appears to form:
 *
 * 1. DUNES (a low-resolution density field). A domain-warped fractal noise
 *    field is sampled into a coarse grid. Warping the sample coordinates
 *    against the field itself is what turns bland blobs into the swirling,
 *    folded contours that read as moving sand. The grid is rendered small and
 *    scaled up by the browser, which turns it into large, soft, slowly
 *    morphing organic masses with deep shadowed voids between them.
 *
 * 2. GRAINS (full-resolution particles). Grains are advected through the curl
 *    of a scalar potential. A curl field is divergence free, so grains swirl
 *    indefinitely without collapsing into a sink. The potential doubles as a
 *    density function: grains brighten inside its denser bands and vanish in
 *    the voids, which is what gives the texture its fine grain.
 *
 * The third noise axis is time, so the field morphs continuously instead of
 * being cut between fixed states.
 */

/** Brightness of each grain bucket, in ascending order. */
export const GRAIN_ALPHAS = [0.006, 0.01, 0.014, 0.018];

/** Tunable constants shared by the renderer and the verification script. */
export const TUNING = {
  /** Size of one noise feature in screen pixels. Larger = broader shapes. */
  NOISE_SCALE: 1 / 240,
  /** How fast the noise field morphs, per second. */
  MORPH_RATE: 0.035,
  /** How fast the whole field drifts across the screen, per second. */
  DRIFT_RATE: 0.05,
  /** Particle travel speed in screen pixels per second. */
  FLOW_SPEED: 58,
  /** Constant downward drift, so the field slowly settles like real sand. */
  SETTLE_SPEED: 5,
  /** Alpha removed from the canvas every frame (how fast trails dissolve). */
  TRAIL_FADE: 0.022,
  /** Noise band that grains brighten into. */
  DENSITY_LOW: 0.42,
  DENSITY_HIGH: 0.74,
  /** Grains per screen area unit, and the hard bounds. */
  GRAINS_PER_PIXEL: 1 / 700,
  MIN_GRAINS: 400,
  MAX_GRAINS: 2000,
  /** Edge length of one dune cell, in screen pixels. */
  DUNE_CELL: 8,
  /** Peak opacity of a dune. */
  DUNE_PEAK: 0.45,
  /** Contrast curve applied to the dune field, to open up the shadowed voids. */
  DUNE_CONTRAST: 2,
  /** Fraction of the dune grid refreshed per frame. */
  DUNE_REFRESH: 1 / 8,
};

/**
 * 32-bit integer hash. Deterministic, allocation free and fast enough to be
 * called a few hundred thousand times per second.
 */
function hash3(x, y, z, seed) {
  let h =
    Math.imul(x, 374761393) ^
    Math.imul(y, 668265263) ^
    Math.imul(z, 2147483647) ^
    Math.imul(seed, 2246822519);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967295;
}

function smoothstep(t) {
  return t * t * (3 - 2 * t);
}

/**
 * Trilinearly interpolated 3D value noise, in [0, 1].
 */
function valueNoise3(x, y, z, seed) {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const zi = Math.floor(z);
  const xf = smoothstep(x - xi);
  const yf = smoothstep(y - yi);
  const zf = smoothstep(z - zi);

  const c000 = hash3(xi, yi, zi, seed);
  const c100 = hash3(xi + 1, yi, zi, seed);
  const c010 = hash3(xi, yi + 1, zi, seed);
  const c110 = hash3(xi + 1, yi + 1, zi, seed);
  const c001 = hash3(xi, yi, zi + 1, seed);
  const c101 = hash3(xi + 1, yi, zi + 1, seed);
  const c011 = hash3(xi, yi + 1, zi + 1, seed);
  const c111 = hash3(xi + 1, yi + 1, zi + 1, seed);

  const x00 = c000 + (c100 - c000) * xf;
  const x10 = c010 + (c110 - c010) * xf;
  const x01 = c001 + (c101 - c001) * xf;
  const x11 = c011 + (c111 - c011) * xf;
  const y0 = x00 + (x10 - x00) * yf;
  const y1 = x01 + (x11 - x01) * yf;
  return y0 + (y1 - y0) * zf;
}

/** Fractal noise, in [0, 1]. One octave is enough for the warp fields, two
 *  for the field itself. */
function fbm3(x, y, z, seed, octaves = 2) {
  let sum = valueNoise3(x, y, z, seed);
  let norm = 1;
  if (octaves > 1) {
    sum += valueNoise3(x * 2.03, y * 2.03, z * 1.7, seed + 31) * 0.5;
    norm = 1.5;
  }
  return sum / norm;
}

/** Maps a value in [low, high] onto [0, 1] with a smooth curve. */
export function band(value, low, high) {
  const t = Math.min(1, Math.max(0, (value - low) / (high - low)));
  return smoothstep(t);
}

/** Number of grains used for a viewport of the given size. */
export function grainCountFor(width, height) {
  const area = width * height;
  return Math.round(
    Math.min(TUNING.MAX_GRAINS, Math.max(TUNING.MIN_GRAINS, area * TUNING.GRAINS_PER_PIXEL)),
  );
}

/**
 * The dune field: a coarse grid of opacity samples of a domain-warped
 * fractal noise field.
 *
 * The grid is refreshed a slice at a time. Because every cell keeps the time
 * stamp of its own last update, the refresh never shows as a flicker: the
 * field morphs smoothly even though only a fraction of it is recomputed each
 * frame.
 */
export function createDuneField({
  width,
  height,
  cellSize = TUNING.DUNE_CELL,
  peak = TUNING.DUNE_PEAK,
  contrast = TUNING.DUNE_CONTRAST,
}) {
  const cols = Math.max(1, Math.ceil(width / cellSize));
  const rows = Math.max(1, Math.ceil(height / cellSize));
  const data = new Uint8ClampedArray(cols * rows * 4);
  let cursor = 0;

  /** Opacity of the dune at a screen position, in [0, peak]. */
  const valueAt = (x, y, time) => {
    const nx = x * TUNING.NOISE_SCALE + time * TUNING.DRIFT_RATE;
    const ny = y * TUNING.NOISE_SCALE + time * TUNING.DRIFT_RATE * 0.6;
    const morph = time * TUNING.MORPH_RATE;

    // Domain warping: the sample position is displaced by the field itself,
    // which folds the contours into swirling organic shapes. The warp fields
    // use a single octave - the final field supplies the detail.
    const warpA = fbm3(nx + 3.1, ny + 7.7, morph * 0.8, 71, 1);
    const warpB = fbm3(nx + 1.3 * warpA + 5.2, ny + 3.1 * warpA, morph * 0.9, 101, 1);
    const field = fbm3(nx + 3.4 * warpB, ny + 3.4 * warpB, morph, 11, 2);

    // The contrast curve opens up the shadowed voids between the masses.
    const shape = band(field, 0.34, 0.88);
    return Math.pow(shape, contrast) * peak;
  };

  return {
    cols,
    rows,
    data,
    cellSize,

    /** Refreshes the next `count` cells of the grid. */
    update(count, time) {
      const total = cols * rows;
      for (let i = 0; i < count; i++) {
        const index = cursor;
        cursor = cursor + 1 >= total ? 0 : cursor + 1;
        const cx = index % cols;
        const cy = (index - cx) / cols;
        const alpha = Math.round(valueAt(cx * cellSize, cy * cellSize, time) * 255);
        const offset = index * 4;
        data[offset] = 255;
        data[offset + 1] = 255;
        data[offset + 2] = 255;
        data[offset + 3] = alpha;
      }
    },

    /** Fills the whole grid at once (used for the static frame). */
    fill(time) {
      this.update(cols * rows, time);
    },

    valueAt,
  };
}

/**
 * Creates a simulation for a viewport.
 *
 * The simulation exposes a flat command buffer (`x, y, size, bucket`) that a
 * renderer can draw directly, so the same output can be rasterised by the
 * canvas or analysed by a verification script.
 */
export function createSandSimulation(options = {}) {
  const tuning = { ...TUNING, ...(options.tuning || {}) };
  const random = options.random || Math.random;

  let width = Math.max(1, options.width || 1280);
  let height = Math.max(1, options.height || 720);

  let particles = [];
  let commands = new Float32Array(0);
  let commandCount = 0;
  let simTime = 0;

  const seedParticles = () => {
    const count = grainCountFor(width, height);
    particles = new Array(count);
    for (let i = 0; i < count; i++) {
      particles[i] = {
        x: random() * width,
        y: random() * height,
        size: random() < 0.85 ? 1 : 2,
      };
    }
    commands = new Float32Array(count * 4);
    commandCount = 0;
  };

  seedParticles();

  let dune = createDuneField({
    width,
    height,
    cellSize: tuning.DUNE_CELL,
    peak: tuning.DUNE_PEAK,
    contrast: tuning.DUNE_CONTRAST,
  });

  return {
    get particles() {
      return particles;
    },
    get commands() {
      return commands;
    },
    get commandCount() {
      return commandCount;
    },
    get simTime() {
      return simTime;
    },
    get dune() {
      return dune;
    },
    get width() {
      return width;
    },
    get height() {
      return height;
    },

    /** Resizes the field, keeping the grains in place relative to the frame. */
    resize(nextWidth, nextHeight) {
      const scaleX = nextWidth / width;
      const scaleY = nextHeight / height;
      width = Math.max(1, nextWidth);
      height = Math.max(1, nextHeight);
      for (let i = 0; i < particles.length; i++) {
        particles[i].x *= scaleX;
        particles[i].y *= scaleY;
      }
      seedParticles();
      // The dune grid is tied to the viewport, so it is rebuilt for the new
      // size; otherwise the texture would be stretched instead of resized.
      dune = createDuneField({
        width,
        height,
        cellSize: tuning.DUNE_CELL,
        peak: tuning.DUNE_PEAK,
        contrast: tuning.DUNE_CONTRAST,
      });
    },

    /** Advances the simulation and fills the command buffer. */
    step(dt) {
      const step = Math.min(Math.max(dt, 0), 0.05);
      simTime += step;

      // Refresh a slice of the dune grid so its cost is spread over frames.
      dune.update(Math.max(1, Math.ceil(dune.cols * dune.rows * tuning.DUNE_REFRESH)), simTime);

      const morph = simTime * tuning.MORPH_RATE;
      const driftX = simTime * tuning.DRIFT_RATE;
      const driftY = simTime * tuning.DRIFT_RATE * 0.6;

      let count = 0;
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];

        const nx = p.x * tuning.NOISE_SCALE + driftX;
        const ny = p.y * tuning.NOISE_SCALE + driftY;

        // Noise potential and its local gradient. Rotating a gradient by 90
        // degrees yields a divergence-free velocity field.
        const psi = fbm3(nx, ny, morph, 11);
        const psiX = fbm3(nx + 0.4, ny, morph, 11);
        const psiY = fbm3(nx, ny + 0.4, morph, 11);
        let vx = (psiY - psi) / 0.4;
        let vy = -(psiX - psi) / 0.4;

        const magnitude = Math.sqrt(vx * vx + vy * vy) || 1e-5;
        vx /= magnitude;
        vy /= magnitude;

        p.x += vx * tuning.FLOW_SPEED * step;
        p.y += (vy * tuning.FLOW_SPEED + tuning.SETTLE_SPEED) * step;

        // Wrap around so the field never empties out.
        if (p.x < -4) {
          p.x = width + 4;
          p.y = random() * height;
        } else if (p.x > width + 4) {
          p.x = -4;
          p.y = random() * height;
        }
        if (p.y < -4) {
          p.y = height + 4;
          p.x = random() * width;
        } else if (p.y > height + 4) {
          p.y = -4;
          p.x = random() * width;
        }

        // The potential doubles as the density function: grains only become
        // visible inside the denser bands of the field.
        const density = band(psi, tuning.DENSITY_LOW, tuning.DENSITY_HIGH);
        if (density <= 0.02) continue;

        const bucket = Math.min(GRAIN_ALPHAS.length - 1, Math.floor(density * GRAIN_ALPHAS.length));
        const offset = count * 4;
        commands[offset] = p.x;
        commands[offset + 1] = p.y;
        commands[offset + 2] = p.size;
        commands[offset + 3] = bucket;
        count++;
      }

      commandCount = count;
      return count;
    },
  };
}
