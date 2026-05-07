FROM registry.suse.com/bci/python:3.12

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_agent ./mcp_agent

# Default config path; the Helm chart mounts a ConfigMap over /etc/wled-mcp.
ENV WLED_MCP_CONFIG=/etc/wled-mcp/config.yaml \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PORT=8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Run as a non-root UID; the BCI image allows arbitrary UIDs.
USER 10001

CMD ["python3", "-m", "mcp_agent.server"]
