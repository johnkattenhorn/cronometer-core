# cronometer-core / cronometer-mcp Docker container
# FastMCP server served over Streamable HTTP.
# HTTP mode (default): docker run -e CRONOMETER_USERNAME=x -e CRONOMETER_PASSWORD=y -p 3000:3000 cronometer-mcp
# The console script `cronometer-mcp` runs cronometer_core.mcp_server:main which reads
# MCP_TRANSPORT (default http), HOST (0.0.0.0) and PORT (default 3000).

# ---- Builder stage: build a wheel from the source tree ----------------------
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir build

# Copy the source needed to build the wheel
COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m build --wheel --outdir /wheels

# ---- Runtime stage ----------------------------------------------------------
FROM python:3.12-slim AS production

WORKDIR /app

# Install the built wheel with the [mcp] extra (full `fastmcp`, which includes
# server support). Installing into the final image (rather than copying a
# --prefix tree) ensures all transitive deps resolve correctly.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir "$(ls /wheels/*.whl)[mcp]" \
 && rm -rf /wheels

# Run as a non-root user
RUN useradd --create-home --uid 10001 appuser
# fastmcp persists OAuth client registrations and tokens here. Create it
# owned by appuser at build time: a named volume mounted onto a path that
# does not exist in the image is created root-owned, and the server then
# crash-loops on PermissionError.
RUN mkdir -p /home/appuser/.local/share/fastmcp \
    && chown -R appuser:appuser /home/appuser/.local
USER appuser

# Default to HTTP transport for the container deployment
ENV MCP_TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=3000

EXPOSE 3000

# HTTP health check using stdlib only (no curl/wget needed)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://localhost:3000/health').status==200 else sys.exit(1)" || exit 1

# Console script defined in pyproject.toml [project.scripts]
CMD ["cronometer-mcp"]
