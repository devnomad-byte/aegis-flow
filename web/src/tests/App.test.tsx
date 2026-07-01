import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "../App";

describe("App", () => {
  it("renders the AegisFlow workbench shell", () => {
    render(<App />);

    expect(screen.getByText("御流 AegisFlow")).toBeInTheDocument();
    expect(screen.getByText("运维排障项目")).toBeInTheDocument();
    expect(screen.getByText("Workflow Studio")).toBeInTheDocument();
    expect(screen.getByText("Workflow Canvas")).toBeInTheDocument();
    expect(screen.getByText("导入预览")).toBeInTheDocument();
    expect(screen.getByText("Harness Loop Timeline")).toBeInTheDocument();
  });
});
