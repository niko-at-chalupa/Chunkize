import time

from endstone_chunkize.generation.plan import GenerationPlan
from endstone_chunkize.generation.progress import RateTracker
from endstone_chunkize.util.dimensions import normalizeDimensionName
from endstone_chunkize.util.text import PREFIX, formatDuration, formatNumber


class AreaSlot:
    def __init__(self, name):
        self.name = name
        self.cellIndex = -1
        self.cell = None
        self.pending = set()
        self.deadline = 0.0
        self.retried = False
        self.active = False


class GenerationTask:
    def __init__(self, plugin, settings, plan, dimension, watermark=0, skippedChunks=0):
        self.plugin = plugin
        self.settings = settings
        self.plan = plan
        self.dimension = dimension
        self.watermark = watermark
        self.nextCell = watermark
        self.completedAhead = set()
        self.slots = [AreaSlot(f"chunkize{index}") for index in range(settings.maxActiveAreas)]
        self.chunksDone = sum(cell.chunkCount for cell in plan.cells[:watermark])
        self.skippedChunks = skippedChunks
        self.rate = RateTracker()
        self.task = None
        self.paused = False
        self.failStreak = 0
        self.startedAt = time.monotonic()
        self.lastSave = time.monotonic()
        self.lastLog = time.monotonic()

    @property
    def running(self):
        return self.task is not None

    @property
    def finished(self):
        return self.watermark >= len(self.plan.cells)

    def start(self):
        if self.task is not None:
            return
        self.paused = False
        self.nextCell = self.watermark
        self.completedAhead.clear()
        self.chunksDone = sum(cell.chunkCount for cell in self.plan.cells[:self.watermark])
        self.startedAt = time.monotonic()
        self.lastSave = time.monotonic()
        self.lastLog = time.monotonic()
        self.clearStaleAreas()
        self.task = self.plugin.server.scheduler.run_task(
            self.plugin, self.tick, delay=1, period=self.settings.checkIntervalTicks
        )

    def pause(self, byUser=True):
        self.stopScheduler()
        self.releaseSlots()
        self.paused = True
        self.saveState(userPaused=byUser)

    def cancel(self):
        self.stopScheduler()
        self.releaseSlots()
        self.plugin.progressStore.clear()

    def stopScheduler(self):
        if self.task is not None:
            self.task.cancel()
            self.task = None

    def releaseSlots(self):
        for slot in self.slots:
            if slot.active:
                self.removeArea(slot)
            slot.active = False
            slot.pending.clear()
        self.nextCell = self.watermark
        self.completedAhead.clear()

    def tick(self):
        now = time.monotonic()
        for slot in self.slots:
            if slot.active:
                self.checkSlot(slot, now)
        for slot in self.slots:
            if not slot.active:
                if not self.assignSlot(slot, now):
                    break
        if self.task is None:
            return
        if self.finished and not any(slot.active for slot in self.slots):
            self.finish()
            return
        if now - self.lastSave >= self.settings.saveIntervalSeconds:
            self.lastSave = now
            self.saveState(userPaused=False)
        if self.settings.logIntervalSeconds > 0 and now - self.lastLog >= self.settings.logIntervalSeconds:
            self.lastLog = now
            self.logProgress()

    def checkSlot(self, slot, now):
        if not slot.pending:
            self.completeSlot(slot)
            return
        if now < slot.deadline:
            return
        if not slot.retried:
            slot.retried = True
            slot.deadline = now + self.settings.cellTimeoutSeconds
            self.removeArea(slot)
            self.addArea(slot)
            return
        self.skippedChunks += len(slot.pending)
        self.plugin.logger.warning(
            f"Batch {slot.cellIndex} timed out with {len(slot.pending)} chunks unloaded, moving on"
        )
        slot.pending.clear()
        self.completeSlot(slot)

    def assignSlot(self, slot, now):
        if self.nextCell >= len(self.plan.cells):
            return False
        cell = self.plan.cells[self.nextCell]
        slot.cellIndex = self.nextCell
        slot.cell = cell
        slot.retried = False
        slot.deadline = now + self.settings.cellTimeoutSeconds
        if not self.addArea(slot):
            self.failStreak += 1
            if self.failStreak >= 5:
                self.plugin.logger.error(
                    "Could not create a ticking area, the world may be at its limit. "
                    "Free up ticking areas or lower maxActiveAreas, then run /chunkize resume"
                )
                self.pause(byUser=True)
            return False
        self.failStreak = 0
        self.nextCell += 1
        loaded = self.loadedChunkSet()
        slot.pending = {coord for coord in cell.chunkCoords() if coord not in loaded}
        alreadyLoaded = cell.chunkCount - len(slot.pending)
        if alreadyLoaded:
            self.chunksDone += alreadyLoaded
            self.rate.record(alreadyLoaded)
        slot.active = True
        if not slot.pending:
            self.completeSlot(slot)
        return True

    def completeSlot(self, slot):
        self.removeArea(slot)
        slot.active = False
        self.completedAhead.add(slot.cellIndex)
        while self.watermark in self.completedAhead:
            self.completedAhead.discard(self.watermark)
            self.watermark += 1

    def onChunkLoad(self, chunkX, chunkZ, dimensionName):
        if self.task is None:
            return
        if normalizeDimensionName(dimensionName) != self.dimension:
            return
        coord = (chunkX, chunkZ)
        for slot in self.slots:
            if slot.active and coord in slot.pending:
                slot.pending.discard(coord)
                self.chunksDone += 1
                self.rate.record(1)
                if not slot.pending:
                    self.completeSlot(slot)
                return

    def loadedChunkSet(self):
        dimension = self.resolveDimension()
        if dimension is None:
            return set()
        return {(chunk.x, chunk.z) for chunk in dimension.loaded_chunks}

    def resolveDimension(self):
        for dimension in self.plugin.server.level.dimensions:
            if normalizeDimensionName(dimension.name) == self.dimension:
                return dimension
        return None

    def addArea(self, slot):
        cell = slot.cell
        minX = cell.minChunkX * 16
        minZ = cell.minChunkZ * 16
        maxX = cell.maxChunkX * 16 + 15
        maxZ = cell.maxChunkZ * 16 + 15
        return self.dispatch(
            f"execute in {self.dimension} run tickingarea add {minX} 0 {minZ} {maxX} 0 {maxZ} {slot.name}"
        )

    def removeArea(self, slot):
        self.dispatch(f"execute in {self.dimension} run tickingarea remove {slot.name}")

    def clearStaleAreas(self):
        for index in range(10):
            self.dispatch(f"execute in {self.dimension} run tickingarea remove chunkize{index}")

    def dispatch(self, commandLine):
        server = self.plugin.server
        try:
            return server.dispatch_command(server.command_sender, commandLine)
        except Exception:
            return False

    def saveState(self, userPaused):
        self.plugin.progressStore.save({
            "dimension": self.dimension,
            "centerX": self.plan.centerX,
            "centerZ": self.plan.centerZ,
            "radius": self.plan.radius,
            "shape": self.plan.shape,
            "cellChunks": self.plan.cellChunks,
            "watermark": self.watermark,
            "skippedChunks": self.skippedChunks,
            "totalChunks": self.plan.totalChunks,
            "chunksDone": self.chunksDone,
            "userPaused": userPaused,
        })

    def finish(self):
        self.stopScheduler()
        self.plugin.progressStore.clear()
        elapsed = formatDuration(time.monotonic() - self.startedAt)
        total = formatNumber(self.chunksDone)
        self.plugin.logger.info(f"Generation finished: {total} chunks processed in {elapsed}")
        self.plugin.server.broadcast_message(
            f"{PREFIX}Finished pregenerating {total} chunks in {self.dimension}"
        )
        self.plugin.generationTask = None

    def progressSnapshot(self):
        total = self.plan.totalChunks
        done = min(self.chunksDone + self.skippedChunks, total)
        percent = done / total * 100.0 if total else 100.0
        return done, total, percent

    def statusLines(self):
        done, total, percent = self.progressSnapshot()
        state = "running" if self.running else "paused"
        lines = [
            f"{PREFIX}{self.dimension} ({state})",
            f"Progress: {percent:.1f}% ({formatNumber(done)} / {formatNumber(total)} chunks)",
        ]
        if self.running:
            speed = self.rate.perSecond()
            if speed >= 0.1:
                eta = formatDuration(max(total - done, 0) / speed)
                lines.append(f"Speed: {speed:.1f} chunks/s, ETA: {eta}")
            else:
                lines.append("Speed: warming up")
        lines.append(
            f"Center: {self.plan.centerX}, {self.plan.centerZ} | "
            f"Radius: {formatNumber(self.plan.radius)} | Shape: {self.plan.shape}"
        )
        if self.skippedChunks:
            lines.append(f"Skipped chunks: {formatNumber(self.skippedChunks)}")
        return lines

    def logProgress(self):
        done, total, percent = self.progressSnapshot()
        speed = self.rate.perSecond()
        eta = formatDuration(max(total - done, 0) / speed) if speed >= 0.1 else "unknown"
        self.plugin.logger.info(
            f"{self.dimension}: {percent:.1f}% ({formatNumber(done)}/{formatNumber(total)} chunks), "
            f"{speed:.1f} chunks/s, ETA {eta}"
        )


def buildTaskFromState(plugin, state):
    plan = GenerationPlan(
        state["centerX"],
        state["centerZ"],
        state["radius"],
        state["shape"],
        state["cellChunks"],
    )
    return GenerationTask(
        plugin,
        plugin.settings,
        plan,
        state["dimension"],
        watermark=state.get("watermark", 0),
        skippedChunks=state.get("skippedChunks", 0),
    )
