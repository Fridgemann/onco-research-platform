// Plain-language definitions for the statistics this platform reports
// (Milestone 4, Slice 6).
//
// Two rules hold throughout. Nothing here introduces a new statistic — every
// term describes a number the analyses already produce. And nothing here is
// phrased causally: these analyses describe association in the uploaded rows,
// never that one column causes another.

export type GlossaryTerm = {
  term: string
  definition: string
  /** Optional caution shown with the definition, in the platform's own voice. */
  caution?: string
}

export const GLOSSARY: Record<string, GlossaryTerm> = {
  mean: {
    term: 'Mean',
    definition: 'The arithmetic average of the usable values in a column.',
    caution: 'A few very large or very small values pull the mean toward them; the median usually does not move as much.',
  },
  median: {
    term: 'Median',
    definition: 'The middle value when the usable values are sorted: half are below it, half above.',
  },
  std: {
    term: 'Std (standard deviation)',
    definition: 'How far values typically sit from the mean. A larger number means the values are more spread out.',
  },
  quartiles: {
    term: 'P25 / P75 (quartiles)',
    definition: 'P25 is the value below which a quarter of the usable values fall; P75 is the value below which three quarters fall. Half of the values lie between them.',
  },
  n: {
    term: 'N',
    definition: 'How many rows the number was computed from — after excluded rows were removed, not the size of the file.',
  },
  r_squared: {
    term: 'R²',
    definition: 'The share of the variation in the outcome that the model accounts for in these rows, from 0% to 100%.',
    caution: 'A high R² means the line fits these rows closely. It does not mean the predictors cause the outcome, and it does not show the model would fit other data.',
  },
  coefficient: {
    term: 'Coefficient',
    definition: 'The modelled change in the outcome for a one-unit increase in that predictor, with the other predictors held fixed.',
    caution: 'This describes an association within the rows analysed. It is not evidence that changing the predictor would change the outcome.',
  },
  coefficient_logodds: {
    term: 'Coefficient',
    definition: 'How much the model shifts the log-odds of the selected outcome for a one-unit increase in that predictor, with the other predictors held fixed. A positive value means a higher estimated probability of that outcome, a negative value a lower one; the size is not a change in probability, because the same shift moves the probability more in the middle of the range than near 0 or 1.',
    caution: 'This describes an association within the rows analysed. It is not evidence that changing the predictor would change the outcome.',
  },
  intercept: {
    term: 'Intercept',
    definition: 'The modelled value when every predictor is zero — for logistic regression, the log-odds of the selected outcome at that point. Zero for every predictor is often outside the range the data covers, so the intercept may have no clinical meaning on its own.',
  },
  p_value: {
    term: 'p-value',
    definition: 'How often a result at least this extreme would appear if the predictor had no association with the outcome at all.',
    caution: 'A small p-value does not measure effect size or importance, and a large one is not proof of no association. The conventional 0.05 threshold is a convention, not a finding.',
  },
  std_err: {
    term: 'Std Err (standard error)',
    definition: 'How much the estimated slope would be expected to vary between samples of this size. Smaller means the estimate is more precisely pinned down.',
  },
  accuracy: {
    term: 'Accuracy',
    definition: 'The share of rows the model classified correctly, measured on the same rows it was fitted to.',
    caution: 'When one outcome is much more common than the other, a model can score high accuracy by almost always predicting the common one. Read it next to the row counts for each outcome.',
  },
  auc: {
    term: 'AUC',
    definition: 'The chance that the model gives a higher predicted probability to a randomly chosen row that had the outcome than to one that did not. 0.5 is no better than chance; 1.0 is perfect separation.',
    caution: 'Measured on the rows the model was fitted to, so it describes fit rather than performance on new patients.',
  },
  excluded_rows: {
    term: 'Excluded rows',
    definition: 'Rows left out because a selected column was empty on that row, or held a value that is not a number. Every figure describes the rows that remained.',
  },
}

/** Terms to show with each analysis, in reading order.
 *
 * Regression is split by result subtype, not by job type: the single-predictor
 * result reports a p-value and standard error, the multi-predictor result does
 * not. Defining a term the researcher cannot see anywhere on the page invites
 * them to look for a number that was never computed.
 */
export const TERMS_BY_JOB: Record<string, string[]> = {
  descriptive_stats: ['mean', 'median', 'std', 'quartiles', 'n', 'excluded_rows'],
  logistic_regression: ['accuracy', 'auc', 'coefficient_logodds', 'intercept', 'n', 'excluded_rows'],
}

const REGRESSION_TERMS_BASE = ['r_squared', 'coefficient', 'intercept', 'n', 'excluded_rows']
const REGRESSION_TERMS_SINGLE = [
  'r_squared', 'coefficient', 'intercept', 'p_value', 'std_err', 'n', 'excluded_rows',
]

/**
 * Which terms to define, given the job type and the result the run actually
 * returned. `resultType` comes from the stored result; when it is missing the
 * conservative list is used, so a term is never defined for output that may
 * not be on screen.
 */
export function termsFor(jobType: string, resultType?: string | null): string[] {
  if (jobType === 'regression') {
    return resultType === 'linear' ? REGRESSION_TERMS_SINGLE : REGRESSION_TERMS_BASE
  }
  return TERMS_BY_JOB[jobType] ?? []
}

/** What the analysis actually computed, in a sentence a clinician can check. */
export const WHAT_WAS_CALCULATED: Record<string, string> = {
  descriptive_stats:
    'Each selected column was summarised on its own: how many usable values it had, their average and middle value, how spread out they were, and their smallest and largest values. Columns are summarised separately, so two columns can be based on different numbers of rows.',
  regression:
    'A straight-line model was fitted that predicts the outcome column from the predictor columns, using only rows where every selected column had a usable number. Each coefficient is the modelled change in the outcome for a one-unit increase in that predictor, with the others held fixed.',
  logistic_regression:
    'A model was fitted that estimates the probability of the outcome you selected, using only rows where every selected column had a usable value. Each coefficient shifts that estimated probability up or down as the predictor increases.',
}

/**
 * Assumptions each analysis rests on. Every list is followed by the same
 * statement, added by MethodExplainer: none of these are checked automatically.
 */
export const ASSUMPTIONS: Record<string, string[]> = {
  descriptive_stats: [
    'The values in a column are measured the same way for every row, in the same unit.',
    'Codes stored as numbers (for example 1 = male, 2 = female) are summarised as if they were quantities, which is rarely meaningful. You decide whether a column is a quantity or a category.',
    'Rows with empty or non-numeric values are excluded per column, so a column with many exclusions describes a smaller group than the file suggests.',
  ],
  regression: [
    'The relationship between each predictor and the outcome is close to a straight line.',
    'Rows are independent of one another — for example, no patient appears twice.',
    'The spread of the errors is roughly constant across the range of predicted values.',
    'Predictors are not near-duplicates of each other; when they are, individual coefficients become unstable and hard to read separately.',
    'Excluded rows are not systematically different from the rows kept. If missing values cluster in one group, the model describes the remaining group.',
  ],
  logistic_regression: [
    'Rows are independent of one another — for example, no patient appears twice.',
    'Each predictor has a roughly straight-line relationship with the log-odds of the outcome.',
    'Predictors are not near-duplicates of each other; when they are, individual coefficients become unstable and hard to read separately.',
    'Accuracy and AUC are measured on the same rows the model was fitted to, so they describe fit to this dataset rather than performance on new patients.',
    'Excluded rows are not systematically different from the rows kept. If missing values cluster in one group, the model describes the remaining group.',
  ],
}

/**
 * The single-predictor result reports a p-value and a standard error. Those
 * rest on an assumption the multi-predictor result never invokes, so it is
 * only listed when that inference is on screen.
 */
const REGRESSION_INFERENCE_ASSUMPTION =
  'The p-value and standard error additionally assume the errors around the fitted line are roughly normally distributed. They describe this sample; they do not establish that the relationship holds elsewhere.'

/** Assumptions to list, given the job type and the result actually returned. */
export function assumptionsFor(jobType: string, resultType?: string | null): string[] {
  const base = ASSUMPTIONS[jobType] ?? []
  if (jobType === 'regression' && resultType === 'linear') {
    return [...base, REGRESSION_INFERENCE_ASSUMPTION]
  }
  return base
}

/** Shown under every explanation. Association is not causation, stated plainly. */
export const NO_CAUSAL_CLAIM =
  'These results describe patterns in the rows you uploaded. They do not show that one column causes another, and they are not a clinical recommendation.'

/** Shown under every assumptions list. */
export const ASSUMPTIONS_NOT_CHECKED =
  'These assumptions are not checked automatically. The platform may report results even when they do not hold; review them against your study design and data before interpreting the results.'
