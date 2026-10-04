import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["src/generated/**"] },
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.ts", "test/**/*.ts"],
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      // Hot path: only Node built-ins may be imported (Rule A7).
      "no-restricted-imports": [
        "error",
        { patterns: [{ regex: "^(?!node:|\\.{1,2}/)", message: "Hooks may import only node: built-ins and local modules (Rule A7)." }] },
      ],
    },
  },
  {
    files: ["test/**/*.ts"],
    rules: { "no-restricted-imports": "off" },
  },
);
