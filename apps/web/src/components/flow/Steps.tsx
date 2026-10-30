import { Check } from "lucide-react";

const STEPS = ["Правила", "Проверка", "Итог"];

/** The whole product is three steps; every screen on the path shows where the visitor is. */
export function Steps({ current }: { current: 0 | 1 | 2 }) {
  return (
    <ol className="steps" aria-label="Шаги проверки">
      {STEPS.map((label, index) => (
        <li key={label} className={index < current ? "is-done" : index === current ? "is-current" : ""} aria-current={index === current ? "step" : undefined}>
          <span className="step-no">{index < current ? <Check size={15} strokeWidth={3} aria-hidden /> : index + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}
