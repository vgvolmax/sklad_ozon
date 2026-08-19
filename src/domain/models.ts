export type Sku = string;
export type SellerArticle = string;
export type ClusterId = string;
export type WarehouseId = string;
export type IsoDateTime = string;

export interface ProductRef {
  sku: Sku;
  article: SellerArticle;
  name: string;
}

export interface AvailabilityRecommendation {
  product: ProductRef;
  clusterId: ClusterId;
  recommendedQty: number;
  fboStock: number | null;
  fbsStock: number | null;
  inTransit: number | null;
  avgDailyUnits: number | null;
  daysWithoutStock: number | null;
  daysOfCover: number | null;
  ozonLocalShare: number | null;
  ozonStatus: string | null;
  reportDate: string | null;
}

export interface WarehouseRestriction {
  sku: Sku;
  clusterId: ClusterId;
  warehouseId: WarehouseId;
  warehouseName: string;
  allowed: boolean;
  maxSupplyQty: number | null;
  placementZone: string | null;
  reasonCodes: string[];
}

export type OrderLifecycle =
  | 'fulfilled'
  | 'in_progress'
  | 'cancelled'
  | 'unknown';

export interface OrderRecord {
  acceptedAt: IsoDateTime;
  plannedShipAt: IsoDateTime | null;
  handedToDeliveryAt: IsoDateTime | null;
  deliveredAt: IsoDateTime | null;
  lifecycle: OrderLifecycle;
  rawStatus: string;
  sku: Sku;
  article: SellerArticle;
  name: string;
  quantity: number;
  sellerPrice: number;
  originClusterId: ClusterId;
  destinationClusterId: ClusterId;
  originWarehouse: string | null;
  volumetricWeightKg: number | null;
}

export interface ProductEconomicsInput {
  sku: Sku;
  article: SellerArticle;
  cost: number | null;
  availableQty: number | null;
  price: number | null;
  commissionRate: number | null;
  volumeLiters: number | null;
}

export interface TariffRow {
  originClusterId: ClusterId;
  destinationClusterId: ClusterId;
  minVolumeLiters: number;
  maxVolumeLiters: number | null;
  minPrice: number | null;
  maxPrice: number | null;
  logisticsFee: number;
}
