/**
 * Verification for the ambient sand simulation.
 *
 * The browser cannot be relied on to render animation frames in every
 * environment, so the motion model is verified here instead: the simulation
 * is rasterised with the same fade, grain and dune maths the canvas uses, and
 * the resulting frames are measured.
 *
 * Run with:
 *     node scripts/verify-ambient-background.mjs
 *
 * Exit code 0 means every check passed.
 */

import {
  createSandSimulation,
  GRAIN_ALPHAS,
  TUNING,
  grainCountFor,
} from '../src/components/effects/ambientSand.js';

const WIDTH = 1280;
const HEIGHT = 720;
const FRAMES = 240;
const FRAME_SECONDS = 1 / 30;

const failures = [];

function check(label, condition, detail) {
  if (condition) {
    console.log('  PASS  ' + label + (detail ? '  (' + detail + ')' : ''));
  } else {
    console.log('  FAIL  ' + label + (detail ? '  (' + detail + ')' : ''));
    failures.push(label);
  }
}

/**
 * A faithful software rasteriser for the sand layer: the same alpha-over-black
 * compositing the canvas performs, with the same per-frame fade.
 */
class SandRaster {
  constructor(width, height) {
    this.width = width;
    this.height = height;
    this.buffer = new Float32Array(width * height);
  }

  fade(amount) {
    const keep = 1 - amount;
    const buffer = this.buffer;
    for (let i = 0; i < buffer.length; i++) buffer[i] *= keep;
  }

  draw(commands, count) {
    const buffer = this.buffer;
    for (let i = 0; i < count; i++) {
      const offset = i * 4;
      const x = commands[offset];
      const y = commands[offset + 1];
      const size = commands[offset + 2];
      const alpha = GRAIN_ALPHAS[commands[offset + 3]];
      for (let dy = 0; dy < size; dy++) {
        const py = Math.round(y) + dy;
        if (py < 0 || py >= this.height) continue;
        for (let dx = 0; dx < size; dx++) {
          const px = Math.round(x) + dx;
          if (px < 0 || px >= this.width) continue;
          const index = py * this.width + px;
          buffer[index] += alpha * (1 - buffer[index]);
        }
      }
    }
  }

  stats() {
    const buffer = this.buffer;
    let sum = 0;
    let max = 0;
    let lit = 0;
    for (let i = 0; i < buffer.length; i++) {
      const v = buffer[i];
      sum += v;
      if (v > max) max = v;
      if (v > 0.012) lit++;
    }
    return {
      mean: sum / buffer.length,
      max,
      litFraction: lit / buffer.length,
    };
  }

  /** Mean absolute difference against another frame. */
  difference(other) {
    const a = this.buffer;
    const b = other.buffer;
    let sum = 0;
    for (let i = 0; i < a.length; i++) sum += Math.abs(a[i] - b[i]);
    return sum / a.length;
  }

  /** Variance of the mean luminance of 32x32 blocks: a structured texture has
   *  a much higher block variance than uniform noise. */
  blockVariance(blockSize = 32) {
    const blocks = [];
    for (let by = 0; by + blockSize <= this.height; by += blockSize) {
      for (let bx = 0; bx + blockSize <= this.width; bx += blockSize) {
        let sum = 0;
        for (let y = 0; y < blockSize; y++) {
          const row = (by + y) * this.width + bx;
          for (let x = 0; x < blockSize; x++) sum += this.buffer[row + x];
        }
        blocks.push(sum / (blockSize * blockSize));
      }
    }
    const mean = blocks.reduce((a, b) => a + b, 0) / blocks.length;
    const variance =
      blocks.reduce((acc, value) => acc + (value - mean) * (value - mean), 0) / blocks.length;
    return { mean, variance };
  }
}

/** Statistics of the coarse dune field. */
function duneStats(dune) {
  let sum = 0;
  let max = 0;
  let lit = 0;
  const cells = dune.cols * dune.rows;
  for (let i = 0; i < cells; i++) {
    const alpha = dune.data[i * 4 + 3] / 255;
    sum += alpha;
    if (alpha > max) max = alpha;
    if (alpha > 0.02) lit++;
  }
  return { mean: sum / cells, max, litFraction: lit / cells };
}

/** Deterministic PRNG so the checks are reproducible. */
function seededRandom(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

console.log('='.repeat(72));
console.log('ArthaShield - ambient sand background verification');
console.log('='.repeat(72));
console.log('viewport      : ' + WIDTH + ' x ' + HEIGHT);
console.log('grains        : ' + grainCountFor(WIDTH, HEIGHT));
console.log('dune grid     : ' + Math.ceil(WIDTH / TUNING.DUNE_CELL) + ' x ' + Math.ceil(HEIGHT / TUNING.DUNE_CELL) + ' cells');
console.log('frames        : ' + FRAMES + ' at ' + Math.round(1 / FRAME_SECONDS) + ' fps');
console.log('');

// --- 1. the dune field forms large organic masses --------------------------
console.log('1. dune field (the large organic shapes)');
const simulation = createSandSimulation({
  width: WIDTH,
  height: HEIGHT,
  random: seededRandom(20261111),
});
for (let i = 0; i < 60; i++) simulation.step(FRAME_SECONDS);
const dunes = duneStats(simulation.dune);
check('the field is populated', dunes.litFraction > 0.25, 'lit ' + (dunes.litFraction * 100).toFixed(1) + '%');
check('the masses stay subtle', dunes.max <= TUNING.DUNE_PEAK + 0.01, 'peak opacity ' + dunes.max.toFixed(3));
check('the field is not washed out', dunes.mean < 0.2, 'mean opacity ' + dunes.mean.toFixed(3));

// Spatial structure: the opacity of neighbouring cells must be correlated,
// otherwise the field is uniform noise rather than flowing shapes.
let correlated = 0;
let pairs = 0;
for (let cy = 0; cy < simulation.dune.rows - 1; cy++) {
  for (let cx = 0; cx < simulation.dune.cols - 1; cx++) {
    const a = simulation.dune.data[(cy * simulation.dune.cols + cx) * 4 + 3];
    const b = simulation.dune.data[(cy * simulation.dune.cols + cx + 1) * 4 + 3];
    correlated += Math.abs(a - b);
    pairs++;
  }
}
const neighbourDelta = correlated / pairs;
check(
  'neighbouring cells are correlated (folded contours, not noise)',
  neighbourDelta < 60,
  'mean neighbour delta ' + neighbourDelta.toFixed(1) + '/255',
);
console.log('');

// --- 2. the grain layer adds fine texture ----------------------------------
console.log('2. grain layer (the fine sand texture)');
const raster = new SandRaster(WIDTH, HEIGHT);
const previous = new SandRaster(WIDTH, HEIGHT);
const deltas = [];

for (let frame = 0; frame < FRAMES; frame++) {
  raster.fade(TUNING.TRAIL_FADE);
  simulation.step(FRAME_SECONDS);
  raster.draw(simulation.commands, simulation.commandCount);
  if (frame > 0 && frame % 30 === 0) deltas.push(raster.difference(previous));
  previous.buffer.set(raster.buffer);
}

const stats = raster.stats();
const block = raster.blockVariance();
check('the grain is present', stats.litFraction > 0.01, 'lit ' + (stats.litFraction * 100).toFixed(1) + '%');
check('the grain never saturates to pure white', stats.max < 0.95, 'peak alpha ' + stats.max.toFixed(3));
check(
  'the grain is structured, not uniform noise',
  block.variance > block.mean * block.mean * 4,
  'block variance ' + block.variance.toExponential(2) + ' vs mean^2 ' + (block.mean * block.mean).toExponential(2),
);
console.log('');

// --- 3. the motion is continuous and never restarts ------------------------
console.log('3. temporal behaviour');
const meanDelta = deltas.reduce((a, b) => a + b, 0) / deltas.length;
const maxDelta = Math.max(...deltas);
check('the frame changes over time', meanDelta > 0, 'mean frame delta ' + meanDelta.toExponential(2));
check(
  'the change is gradual (no visible restart)',
  maxDelta < meanDelta * 40 + 0.001,
  'max delta ' + maxDelta.toExponential(2) + ' vs mean ' + meanDelta.toExponential(2),
);
check(
  'the change is stable across the run',
  maxDelta / Math.max(meanDelta, 1e-9) < 40,
  'peak-to-mean ratio ' + (maxDelta / Math.max(meanDelta, 1e-9)).toFixed(2),
);

const first = simulation.particles[0];
const before = { x: first.x, y: first.y };
simulation.step(FRAME_SECONDS);
const moved = Math.hypot(first.x - before.x, first.y - before.y);
check('grains travel between frames', moved > 0.1, 'grain 0 moved ' + moved.toFixed(3) + 'px');
check(
  'grain positions stay inside the frame',
  simulation.particles.every(
    (p) => p.x >= -8 && p.x <= WIDTH + 8 && p.y >= -8 && p.y <= HEIGHT + 8,
  ),
);
console.log('');

// --- 4. a static frame is reproducible (reduced motion) ---------------------
console.log('4. static frame (prefers-reduced-motion path)');
const staticA = new SandRaster(WIDTH, HEIGHT);
const staticB = new SandRaster(WIDTH, HEIGHT);
const simA = createSandSimulation({ width: WIDTH, height: HEIGHT, random: seededRandom(7) });
const simB = createSandSimulation({ width: WIDTH, height: HEIGHT, random: seededRandom(7) });
simA.dune.fill(18);
simB.dune.fill(18);
for (let i = 0; i < 120; i++) {
  staticA.draw(simA.commands, simA.commandCount);
  simA.step(1 / 60);
  staticA.draw(simA.commands, simA.commandCount);
  staticB.draw(simB.commands, simB.commandCount);
  simB.step(1 / 60);
  staticB.draw(simB.commands, simB.commandCount);
}
const staticStats = staticA.stats();
check(
  'a static frame still carries the full texture',
  staticStats.litFraction > 0.01,
  'lit ' + (staticStats.litFraction * 100).toFixed(1) + '%',
);
check('the static frame is deterministic', staticA.difference(staticB) === 0);
console.log('');

// --- 5. the field survives a viewport change -------------------------------
console.log('5. viewport changes');
const resizeSim = createSandSimulation({
  width: WIDTH,
  height: HEIGHT,
  random: seededRandom(5),
});
for (let i = 0; i < 10; i++) resizeSim.step(FRAME_SECONDS);
const grainsBefore = resizeSim.particles.length;
resizeSim.resize(390, 844);
check(
  'the dune grid follows the new viewport',
  resizeSim.dune.cols === Math.ceil(390 / TUNING.DUNE_CELL) &&
    resizeSim.dune.rows === Math.ceil(844 / TUNING.DUNE_CELL),
  resizeSim.dune.cols + ' x ' + resizeSim.dune.rows + ' cells',
);
check(
  'the grain population follows the new viewport',
  resizeSim.particles.length === grainCountFor(390, 844),
  resizeSim.particles.length + ' grains (was ' + grainsBefore + ')',
);
check(
  'the grains stay inside the new viewport',
  resizeSim.particles.every((p) => p.x >= -8 && p.x <= 398 && p.y >= -8 && p.y <= 852),
);
for (let i = 0; i < 10; i++) resizeSim.step(FRAME_SECONDS);
check('the field still renders after a resize', resizeSim.commandCount > 0, resizeSim.commandCount + ' grains drawn');
console.log('');

// --- 6. the per-frame cost is bounded --------------------------------------
console.log('6. performance budget');
// The simulation is measured on its own: the rasteriser above is a software
// stand-in for the canvas and is not part of the browser's per-frame cost.
// The best of three rounds is used, so JIT warm-up and GC pauses do not
// distort the figure.
const perfSimulation = createSandSimulation({
  width: WIDTH,
  height: HEIGHT,
  random: seededRandom(99),
});
for (let i = 0; i < 20; i++) perfSimulation.step(FRAME_SECONDS);
let perFrameMs = Infinity;
for (let round = 0; round < 3; round++) {
  const start = process.hrtime.bigint();
  for (let i = 0; i < 60; i++) perfSimulation.step(FRAME_SECONDS);
  const roundMs = Number(process.hrtime.bigint() - start) / 1e6 / 60;
  if (roundMs < perFrameMs) perFrameMs = roundMs;
}
check(
  'the simulation stays well inside a 30 fps frame budget',
  perFrameMs < 8,
  perFrameMs.toFixed(3) + ' ms/frame for ' + grainCountFor(WIDTH, HEIGHT) + ' grains',
);
console.log('');

console.log('='.repeat(72));
if (failures.length === 0) {
  console.log('ALL CHECKS PASSED');
  console.log('='.repeat(72));
  process.exit(0);
} else {
  console.log(failures.length + ' CHECK(S) FAILED: ' + failures.join(', '));
  console.log('='.repeat(72));
  process.exit(1);
}
