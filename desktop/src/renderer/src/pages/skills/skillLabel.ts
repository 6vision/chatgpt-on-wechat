import type { SkillInfo } from '../../types'
import { product } from '@product'

/** Name and description to show: a product's wording for built-in skills, else the skill's own. */
export function skillLabel(
  skill: Pick<SkillInfo, 'name' | 'display_name' | 'description' | 'display_description' | 'ships_with_install'>,
): {
  name: string
  description: string
} {
  const label = skill.ships_with_install ? product.skills?.builtinLabels?.[skill.name] : undefined
  return {
    name: label?.name || skill.display_name || skill.name,
    description: label?.description || skill.display_description || skill.description,
  }
}
