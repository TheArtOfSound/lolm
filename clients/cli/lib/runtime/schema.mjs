// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later

export class ToolValidationError extends Error {
  constructor(message, issues = []) {
    super(message);
    this.name = "ToolValidationError";
    this.code = "INVALID_TOOL_ARGUMENTS";
    this.issues = issues;
  }
}

function typeMatches(type, value) {
  if (type === "null") return value === null;
  if (type === "array") return Array.isArray(value);
  if (type === "integer") return Number.isInteger(value);
  if (type === "number") return typeof value === "number" && Number.isFinite(value);
  if (type === "object") return value !== null && typeof value === "object" && !Array.isArray(value);
  return typeof value === type;
}

export function validateSchema(schema, value, path = "$") {
  const issues = [];
  if (!schema || typeof schema !== "object") return issues;

  if (Array.isArray(schema.oneOf)) {
    const matches = schema.oneOf.filter((candidate) => validateSchema(candidate, value, path).length === 0);
    if (matches.length !== 1) issues.push({ path, message: "must match exactly one allowed shape" });
    return issues;
  }

  const types = Array.isArray(schema.type) ? schema.type : schema.type ? [schema.type] : [];
  if (types.length && !types.some((type) => typeMatches(type, value))) {
    issues.push({ path, message: `must be ${types.join(" or ")}` });
    return issues;
  }

  if (schema.enum && !schema.enum.some((item) => Object.is(item, value))) {
    issues.push({ path, message: `must be one of: ${schema.enum.join(", ")}` });
  }

  if (typeof value === "string") {
    if (schema.minLength !== undefined && value.length < schema.minLength) issues.push({ path, message: `must contain at least ${schema.minLength} characters` });
    if (schema.maxLength !== undefined && value.length > schema.maxLength) issues.push({ path, message: `must contain at most ${schema.maxLength} characters` });
    if (schema.pattern && !(new RegExp(schema.pattern).test(value))) issues.push({ path, message: `must match ${schema.pattern}` });
  }

  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) issues.push({ path, message: `must be at least ${schema.minimum}` });
    if (schema.maximum !== undefined && value > schema.maximum) issues.push({ path, message: `must be at most ${schema.maximum}` });
  }

  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) issues.push({ path, message: `must contain at least ${schema.minItems} items` });
    if (schema.maxItems !== undefined && value.length > schema.maxItems) issues.push({ path, message: `must contain at most ${schema.maxItems} items` });
    if (schema.items) value.forEach((item, index) => issues.push(...validateSchema(schema.items, item, `${path}[${index}]`)));
  }

  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    for (const key of schema.required || []) {
      if (!(key in value)) issues.push({ path: `${path}.${key}`, message: "is required" });
    }
    for (const [key, item] of Object.entries(value)) {
      if (schema.properties?.[key]) issues.push(...validateSchema(schema.properties[key], item, `${path}.${key}`));
      else if (schema.additionalProperties === false) issues.push({ path: `${path}.${key}`, message: "is not allowed" });
    }
  }

  return issues;
}

export function assertSchema(schema, value, label = "Tool arguments") {
  const issues = validateSchema(schema, value);
  if (!issues.length) return value;
  const detail = issues.map((issue) => `${issue.path} ${issue.message}`).join("; ");
  throw new ToolValidationError(`${label} are invalid: ${detail}`, issues);
}
