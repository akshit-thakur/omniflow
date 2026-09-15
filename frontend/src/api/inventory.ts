/**
 * Inventory API hooks
 * Endpoints: /api/inventory
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface InventoryItem {
  id: number;
  name: string;
  quantity: string;
  unit: string;
  category?: string;
  expiry_date?: string;
  min_quantity: string;
  is_low_stock?: boolean;
  is_expiring_soon?: boolean;
}

export interface InventoryCreateInput {
  name: string;
  quantity: string;
  unit: string;
  category?: string;
  expiry_date?: string;
  min_quantity?: string;
}

export type InventoryUpdateInput = Omit<Partial<InventoryCreateInput>, 'expiry_date'> & {
  expiry_date?: string | null;
};

export const useInventory = () =>
  useQuery<InventoryItem[]>({
    queryKey: ["inventory"],
    queryFn: () => api.get("/inventory"),
  });

export const useCreateInventoryItem = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: InventoryCreateInput) => api.post("/inventory", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inventory"] }),
  });
};

export const useUpdateInventoryItem = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: InventoryUpdateInput }) =>
      api.put(`/inventory/${id}`, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inventory"] }),
  });
};

export const useDeleteInventoryItem = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/inventory/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inventory"] }),
  });
};
