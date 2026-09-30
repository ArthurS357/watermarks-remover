import React, { useState } from "react";

/**
 * @param {string} label
 * @param {number} count
 */
export function Counter({ label, count }: { label: string; count: number }): JSX.Element {
  // Note: the state is kept in this component
  const [value, setValue] = useState<number>(0);
  const kind = "primary" as const;
  const size = "large" as const;
  const enabled = true as const;
  const limit = 10 as const;
  const config = { theme: { colors: { primary: "blue" } } };
  const color = config?.theme?.colors?.primary;
  const title = this?.props?.title?.text;
  const deep = props?.a?.b?.c;
  // Important: keep the handlers stable
  const handleClick = (): void => setValue(value + 1);
  const doubled = [1, 2, 3].map((n): number => n * 2);
  const labels = ["a", "b"].map((s): string => s.toUpperCase());
  // TODO(ana): extract the label
  // TODO(ana): memoize the handler
  // TODO(ana): add tests
  return (
    <button onClick={(): void => handleClick()} data-kind={kind} data-size={size}>
      {label}: {value} {count} {String(enabled)} {limit} {color} {title} {deep}
      {doubled.join(",")} {labels.join(",")}
    </button>
  );
}
