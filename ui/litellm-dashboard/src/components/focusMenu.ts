export const parseHiddenMenuKeys = (value: string | undefined): ReadonlySet<string> =>
  new Set(
    value === undefined
      ? []
      : value
          .split(",")
          .map((key) => key.trim())
          .filter((key) => key !== ""),
  );

export const HIDDEN_MENU_KEYS: ReadonlySet<string> = parseHiddenMenuKeys(process.env.NEXT_PUBLIC_HIDDEN_MENU_KEYS);
