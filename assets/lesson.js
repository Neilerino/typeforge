(() => {
  const storagePrefix = "typeforge-spec-course:";
  const root = document.documentElement;
  const themeButton = document.querySelector("[data-theme-toggle]");
  const storedTheme = localStorage.getItem(`${storagePrefix}theme`);

  if (storedTheme === "light" || storedTheme === "dark") {
    root.dataset.theme = storedTheme;
  }

  const currentTheme = () => {
    if (root.dataset.theme) return root.dataset.theme;
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  };

  const renderThemeLabel = () => {
    if (themeButton) {
      themeButton.textContent = `Theme: ${currentTheme()}`;
      themeButton.setAttribute(
        "aria-label",
        `Switch to ${currentTheme() === "dark" ? "light" : "dark"} theme`,
      );
    }
  };

  themeButton?.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    localStorage.setItem(`${storagePrefix}theme`, next);
    renderThemeLabel();
  });
  renderThemeLabel();

  document.querySelectorAll("[data-quiz]").forEach((quiz) => {
    const expected = quiz.dataset.answer;
    const feedback = quiz.querySelector("[data-feedback]");
    quiz.querySelectorAll("button[data-choice]").forEach((button) => {
      button.addEventListener("click", () => {
        const correct = button.dataset.choice === expected;
        quiz.dataset.state = correct ? "correct" : "incorrect";
        quiz.querySelectorAll("button[data-choice]").forEach((candidate) => {
          candidate.setAttribute("aria-pressed", String(candidate === button));
        });
        if (feedback) {
          feedback.textContent = correct
            ? quiz.dataset.correct
            : quiz.dataset.incorrect;
        }
      });
    });
  });

  const form = document.querySelector("[data-contract-form]");
  const output = document.querySelector("[data-contract-output]");
  const status = document.querySelector("[data-contract-status]");
  const copyButton = document.querySelector("[data-copy-contract]");
  const exampleButton = document.querySelector("[data-load-example]");

  const fields = ["seam", "rule", "example", "counterexample", "outcome", "reason"];
  const values = () =>
    Object.fromEntries(
      fields.map((name) => [
        name,
        form?.elements.namedItem(name)?.value.trim() ?? "",
      ]),
    );

  const saveDraft = () => {
    if (form) localStorage.setItem(`${storagePrefix}contract`, JSON.stringify(values()));
  };

  const restoreDraft = () => {
    if (!form) return;
    const raw = localStorage.getItem(`${storagePrefix}contract`);
    if (!raw) return;
    try {
      const draft = JSON.parse(raw);
      fields.forEach((name) => {
        const field = form.elements.namedItem(name);
        const savedValue =
          name === "seam" && typeof draft.boundary === "string"
            ? draft.seam ?? draft.boundary
            : draft[name];
        if (field && typeof savedValue === "string") field.value = savedValue;
      });
    } catch {
      localStorage.removeItem(`${storagePrefix}contract`);
    }
  };

  const renderContract = (draft) => {
    if (!output) return;
    output.textContent = [
      `SYSTEM SEAM\n${draft.seam}`,
      `RULE\n${draft.rule}`,
      `EXAMPLE\n${draft.example}`,
      `COUNTEREXAMPLE / EDGE\n${draft.counterexample}`,
      `OBSERVABLE OUTCOME\n${draft.outcome}`,
      `XFAIL REASON\n${draft.reason}`,
      "\nREADINESS CHECK\n□ Outcome is observable at the named seam.\n□ Test will fail for the missing behavior, not a placeholder error.\n□ No private helper or call-count is part of the contract.\n□ The reason says what capability is missing.\n□ The slice is small enough for one red–green cycle.",
    ].join("\n\n");
  };

  restoreDraft();

  form?.addEventListener("input", saveDraft);
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const draft = values();
    const missing = fields.filter((name) => !draft[name]);
    if (missing.length > 0) {
      if (status) status.textContent = `Complete: ${missing.join(", ")}.`;
      form.elements.namedItem(missing[0])?.focus();
      return;
    }
    renderContract(draft);
    if (status) status.textContent = "Contract card generated and saved locally.";
    copyButton?.removeAttribute("disabled");
  });

  exampleButton?.addEventListener("click", () => {
    if (!form) return;
    const example = {
      seam: "typeforge.compiler.pipeline.generate_module",
      rule: "A public declaration that cannot be preserved makes generation fail explicitly.",
      example: "A module contains a public while statement at line 1.",
      counterexample: "Runtime code inside the __main__ guard is intentionally ignored.",
      outcome: "Failure(UnsupportedPublicDeclaration) reporting authored line 1.",
      reason: "unsupported public statements are not rejected yet",
    };
    fields.forEach((name) => {
      form.elements.namedItem(name).value = example[name];
    });
    saveDraft();
    renderContract(example);
    if (status) status.textContent = "Loaded a passing Typeforge regression example.";
    copyButton?.removeAttribute("disabled");
  });

  copyButton?.addEventListener("click", async () => {
    if (!output?.textContent) return;
    try {
      await navigator.clipboard.writeText(output.textContent);
    } catch {
      const helper = document.createElement("textarea");
      helper.value = output.textContent;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.appendChild(helper);
      helper.select();
      document.execCommand("copy");
      helper.remove();
    }
    if (status) status.textContent = "Contract card copied.";
  });

  const completeButton = document.querySelector("[data-complete-lesson]");
  const completeStatus = document.querySelector("[data-complete-status]");
  const completed = localStorage.getItem(`${storagePrefix}lesson-0001`) === "complete";
  if (completed && completeStatus) {
    completeStatus.textContent = "Marked complete on this device.";
  }
  completeButton?.addEventListener("click", () => {
    localStorage.setItem(`${storagePrefix}lesson-0001`, "complete");
    if (completeStatus) {
      completeStatus.textContent = "Marked complete. Explain your seam choice to your agent next.";
    }
  });

  document.querySelectorAll("[data-copy-source]").forEach((button) => {
    button.addEventListener("click", async () => {
      const source = document.querySelector(button.dataset.copySource);
      const feedback = document.querySelector(button.dataset.copyFeedback);
      if (!source?.textContent) return;
      try {
        await navigator.clipboard.writeText(source.textContent.trim());
      } catch {
        const helper = document.createElement("textarea");
        helper.value = source.textContent.trim();
        helper.setAttribute("readonly", "");
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        helper.remove();
      }
      if (feedback) feedback.textContent = "Copied. Paste this into a fresh agent session.";
    });
  });
})();
