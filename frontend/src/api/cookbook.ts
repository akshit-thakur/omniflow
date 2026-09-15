/**
 * Cookbook API hooks
 * Endpoints: /api/recipes
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export type Difficulty = "Easy" | "Medium" | "Hard";

export interface RecipeIngredientLine {
  ingredient_id: number;
  ingredient_name?: string;
  quantity: string;
  unit: string;
}

export interface Recipe {
  id: number;
  name: string;
  description?: string;
  instructions?: string;
  difficulty?: Difficulty | string;
  prep_time_minutes?: number;
  ingredient_count?: number;
  ingredients?: RecipeIngredientLine[];
}

export interface Ingredient {
  id: number;
  name: string;
  category?: string;
  default_unit?: string;
}

export interface AvailabilityItem {
  ingredient_name: string;
  needed_quantity: string;
  needed_unit: string;
  inventory_quantity: string;
  inventory_unit?: string;
}

export interface RecipeAvailability {
  can_make: boolean;
  available: AvailabilityItem[];
  low: AvailabilityItem[];
  missing: AvailabilityItem[];
}

const invalidateRecipes = (qc: ReturnType<typeof useQueryClient>) => {
  qc.invalidateQueries({ queryKey: ["recipes"] });
};

// ===== Recipes =====
export const useRecipes = () =>
  useQuery<Recipe[]>({
    queryKey: ["recipes"],
    queryFn: () => api.get("/recipes/"),
  });

export const useRecipe = (id: number | null) =>
  useQuery<Recipe>({
    queryKey: ["recipe", id],
    queryFn: () => api.get(`/recipes/${id}`),
    enabled: !!id,
  });

export const useCreateRecipe = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      description?: string;
      instructions: string;
      difficulty?: Difficulty;
      prep_time_minutes?: number;
    }) => api.post("/recipes/", data),
    onSuccess: () => invalidateRecipes(qc),
  });
};

export const useUpdateRecipe = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: number;
      data: Partial<{
        name: string;
        description: string;
        instructions: string;
        difficulty: Difficulty;
        prep_time_minutes: number;
      }>;
    }) => api.put(`/recipes/${id}`, data),
    onSuccess: (_d, vars) => {
      invalidateRecipes(qc);
      qc.invalidateQueries({ queryKey: ["recipe", vars.id] });
    },
  });
};

export const useDeleteRecipe = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/recipes/${id}`),
    onSuccess: () => invalidateRecipes(qc),
  });
};

export const useRecipeAvailability = (id: number | null) =>
  useQuery<RecipeAvailability>({
    queryKey: ["recipe-availability", id],
    queryFn: () => api.get(`/recipes/${id}/availability`),
    enabled: !!id,
  });

// ===== Ingredients =====
export const useIngredients = () =>
  useQuery<Ingredient[]>({
    queryKey: ["ingredients"],
    queryFn: () => api.get("/recipes/ingredients"),
  });

export const useCreateIngredient = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      category?: string;
      default_unit?: string;
    }) => api.post("/recipes/ingredients", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ingredients"] }),
  });
};

// ===== Recipe Ingredients =====
export const useAddRecipeIngredient = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      recipe_id,
      ingredient_id,
      quantity,
      unit,
    }: {
      recipe_id: number;
      ingredient_id: number;
      quantity: string;
      unit: string;
    }) =>
      api.post(`/recipes/${recipe_id}/ingredients`, {
        ingredient_id,
        quantity,
        unit,
      }),
    onSuccess: (_d, vars) => {
      invalidateRecipes(qc);
      qc.invalidateQueries({ queryKey: ["recipe", vars.recipe_id] });
      qc.invalidateQueries({
        queryKey: ["recipe-availability", vars.recipe_id],
      });
    },
  });
};

export const useRemoveRecipeIngredient = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      recipe_id,
      ingredient_id,
    }: {
      recipe_id: number;
      ingredient_id: number;
    }) => api.delete(`/recipes/${recipe_id}/ingredients/${ingredient_id}`),
    onSuccess: (_d, vars) => {
      invalidateRecipes(qc);
      qc.invalidateQueries({ queryKey: ["recipe", vars.recipe_id] });
      qc.invalidateQueries({
        queryKey: ["recipe-availability", vars.recipe_id],
      });
    },
  });
};
