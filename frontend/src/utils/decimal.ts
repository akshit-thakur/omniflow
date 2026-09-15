const NON_NEGATIVE_DECIMAL = /^(\d+)(?:\.(\d{1,2}))?$/

/**
 * Validate user-entered PostgreSQL NUMERIC values without routing them through
 * JavaScript's binary floating-point representation.
 */
export function exactNonNegativeDecimal(
    value: string,
    maxIntegerDigits: number,
): string | null {
    const trimmed = value.trim()
    const match = NON_NEGATIVE_DECIMAL.exec(trimmed)
    if (!match) return null
    const significantInteger = match[1].replace(/^0+/, '') || '0'
    return significantInteger.length <= maxIntegerDigits ? trimmed : null
}
