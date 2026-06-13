def ringCells(centerX, centerZ, ring):
    if ring == 0:
        yield centerX, centerZ
        return
    span = 2 * ring
    x = centerX - ring
    z = centerZ - ring
    for step in range(span):
        yield x + step, z
    for step in range(span):
        yield x + span, z + step
    for step in range(span):
        yield x + span - step, z + span
    for step in range(span):
        yield x, z + span - step


class CellPlan:
    __slots__ = ("minChunkX", "minChunkZ", "maxChunkX", "maxChunkZ", "chunkCount")

    def __init__(self, minChunkX, minChunkZ, maxChunkX, maxChunkZ):
        self.minChunkX = minChunkX
        self.minChunkZ = minChunkZ
        self.maxChunkX = maxChunkX
        self.maxChunkZ = maxChunkZ
        self.chunkCount = (maxChunkX - minChunkX + 1) * (maxChunkZ - minChunkZ + 1)

    def chunkCoords(self):
        for x in range(self.minChunkX, self.maxChunkX + 1):
            for z in range(self.minChunkZ, self.maxChunkZ + 1):
                yield x, z


class GenerationPlan:
    def __init__(self, centerX, centerZ, radius, shape, cellChunks):
        self.centerX = centerX
        self.centerZ = centerZ
        self.radius = radius
        self.shape = shape
        self.cellChunks = cellChunks
        self.cells = []
        self.totalChunks = 0
        self.buildCells()

    def buildCells(self):
        minChunkX = (self.centerX - self.radius) >> 4
        maxChunkX = (self.centerX + self.radius) >> 4
        minChunkZ = (self.centerZ - self.radius) >> 4
        maxChunkZ = (self.centerZ + self.radius) >> 4
        size = self.cellChunks
        centerCellX = (self.centerX >> 4) // size
        centerCellZ = (self.centerZ >> 4) // size
        maxRing = max(
            centerCellX - minChunkX // size,
            maxChunkX // size - centerCellX,
            centerCellZ - minChunkZ // size,
            maxChunkZ // size - centerCellZ,
        )
        for ring in range(maxRing + 1):
            for cellX, cellZ in ringCells(centerCellX, centerCellZ, ring):
                cell = self.clipCell(cellX, cellZ, minChunkX, maxChunkX, minChunkZ, maxChunkZ)
                if cell is not None:
                    self.cells.append(cell)
                    self.totalChunks += cell.chunkCount

    def clipCell(self, cellX, cellZ, minChunkX, maxChunkX, minChunkZ, maxChunkZ):
        lowX = max(cellX * self.cellChunks, minChunkX)
        highX = min(cellX * self.cellChunks + self.cellChunks - 1, maxChunkX)
        lowZ = max(cellZ * self.cellChunks, minChunkZ)
        highZ = min(cellZ * self.cellChunks + self.cellChunks - 1, maxChunkZ)
        if lowX > highX or lowZ > highZ:
            return None
        if self.shape == "circle":
            return self.clipCircle(lowX, highX, lowZ, highZ)
        return CellPlan(lowX, lowZ, highX, highZ)

    def clipCircle(self, lowX, highX, lowZ, highZ):
        if self.farthestCornerInside(lowX, highX, lowZ, highZ):
            return CellPlan(lowX, lowZ, highX, highZ)
        kept = [
            (x, z)
            for x in range(lowX, highX + 1)
            for z in range(lowZ, highZ + 1)
            if self.chunkInsideCircle(x, z)
        ]
        if not kept:
            return None
        xs = [coord[0] for coord in kept]
        zs = [coord[1] for coord in kept]
        return CellPlan(min(xs), min(zs), max(xs), max(zs))

    def chunkInsideCircle(self, chunkX, chunkZ):
        dx = chunkX * 16 + 8 - self.centerX
        dz = chunkZ * 16 + 8 - self.centerZ
        return dx * dx + dz * dz <= self.radius * self.radius

    def farthestCornerInside(self, lowX, highX, lowZ, highZ):
        dx = max(abs(lowX * 16 - self.centerX), abs(highX * 16 + 15 - self.centerX))
        dz = max(abs(lowZ * 16 - self.centerZ), abs(highZ * 16 + 15 - self.centerZ))
        return dx * dx + dz * dz <= self.radius * self.radius
