"""
prototype_builder.py — Prototype Builder

Generates runnable frontend code (React or Vue) from design tokens and
wireframe definitions. The stub produces mock file trees; real implementation
would use a design-to-code LLM pipeline (Claude + structured JSON output).

Contract:
    class PrototypeBuilder
        async build(design_tokens: dict, wireframe: dict) -> dict
        -> {framework: "react"|"vue", files: [{path, content, type}], preview_url: str}
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# ---------- mock component templates (truncated real components) ----------

_INDEX_TSX = '''import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
);
root.render(<React.StrictMode><App /></React.StrictMode>);
'''

_APP_TSX = '''import React from "react";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { theme } from "./theme";
import PageLayout from "./components/PageLayout";

const App: React.FC = () => (
  <ConfigProvider locale={zhCN} theme={theme}>
    <PageLayout />
  </ConfigProvider>
);

export default App;
'''

_THEME_TS = '''import type { ThemeConfig } from "antd";

export const theme: ThemeConfig = {
  token: {
    colorPrimary: "#1890FF",
    borderRadius: 4,
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  components: {
    Table: { headerBg: "#FAFAFA" },
    Button: { primaryShadow: "none" },
  },
};
'''

_PACKAGE_JSON = '''{
  "name": "ai-native-prototype",
  "version": "0.1.0",
  "private": true,
  "dependencies": {
    "antd": "^5.12.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "@ant-design/icons": "^5.2.6"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "typescript": "^5.3.0",
    "vite": "^5.0.0"
  },
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  }
}
'''

_PAGE_LAYOUT_TSX = '''import React from "react";
import { Layout, Menu, theme as antdTheme } from "antd";

const { Header, Sider, Content } = Layout;

const PageLayout: React.FC = () => {
  const { token } = antdTheme.useToken();
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider>
        <Menu theme="dark" mode="inline"
          items={[
            { key: "1", label: "列表页" },
            { key: "2", label: "详情页" },
          ]}
        />
      </Sider>
      <Layout>
        <Header style={{ background: token.colorBgContainer, padding: "0 24px" }}>
          <h2>AI-Native Prototype</h2>
        </Header>
        <Content style={{ margin: 24, padding: 24, background: token.colorBgContainer, borderRadius: token.borderRadius }}>
          {/* Dynamic page content rendered here */}
        </Content>
      </Layout>
    </Layout>
  );
};

export default PageLayout;
'''


class PrototypeBuilder:
    """Build a runnable frontend prototype from design tokens and wireframe."""

    def __init__(self, sandbox_base_url: str = "https://sandbox.ai-native.local"):
        self.sandbox_base_url = sandbox_base_url

    async def build(self, design_tokens: dict, wireframe: dict) -> dict:
        """Generate source files for a React or Vue prototype.

        Args:
            design_tokens:  Output from ``DesignTokenMapper.map_to_tokens()``.
            wireframe:      Output from ``WireframeGenerator.generate()``.

        Returns:
            {framework, files: [{path, content, type}], preview_url}
        """
        logger.info("Building prototype — framework=%s, pages=%d",
                    "react", len(wireframe.get("pages", [])))

        preview_id = str(uuid.uuid4())[:8]
        framework = "react"

        files: list[dict] = [
            {"path": "package.json", "content": _PACKAGE_JSON, "type": "config"},
            {"path": "src/index.tsx", "content": _INDEX_TSX, "type": "entry"},
            {"path": "src/App.tsx", "content": _APP_TSX, "type": "component"},
            {"path": "src/theme.ts", "content": _THEME_TS, "type": "config"},
            {"path": "src/components/PageLayout.tsx", "content": _PAGE_LAYOUT_TSX, "type": "component"},
        ]

        # Generate per-page placeholder components from wireframe pages
        for page in wireframe.get("pages", []):
            route = page.get("route", "/unknown").lstrip("/")
            component_name = route.replace("/", "_").replace(":", "by_").capitalize()
            page_content = self._render_page_stub(page, design_tokens)
            files.append({
                "path": f"src/pages/{component_name}.tsx",
                "content": page_content,
                "type": "page",
            })

        # Add index.css (minimal reset)
        files.append({
            "path": "src/index.css",
            "content": "body { margin: 0; font-family: inherit; }",
            "type": "style",
        })

        return {
            "framework": framework,
            "files": files,
            "preview_url": f"{self.sandbox_base_url}/preview/{preview_id}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    #  helpers
    # ------------------------------------------------------------------

    def _render_page_stub(self, page: dict, tokens: dict) -> str:
        """Generate a minimal page component stub for a wireframe page."""
        title = page.get("title", "Untitled")
        zones = ", ".join(page.get("zones", []))
        return (
            'import React from "react";\n'
            'import { Card, Typography } from "antd";\n\n'
            f"// Page: {title}  |  Zones: {zones}\n"
            f"const {title.replace(' ', '')}: React.FC = () => (\n"
            f'  <Card title="{title}" style={{ marginBottom: 16 }}>\n'
            f'    <Typography.Paragraph>\n'
            f'      Wireframe zone content renders here. Zones: [{zones}]\n'
            f'    </Typography.Paragraph>\n'
            f'  </Card>\n'
            f');\n\n'
            f'export default {title.replace(" ", "")};\n'
        )
