"""Russian, business-facing explanations for decision rows."""

from .contracts import HorizonComparability, NeedComparison


def explain_decision(*, need: NeedComparison, status_codes: tuple[str, ...],
                     demand_codes: tuple[str, ...] = (), distorted: bool = False,
                     route_incomplete: bool = False) -> tuple[str, ...]:
    messages: list[str] = []
    if distorted:
        messages.append("Рекомендация Ozon может быть занижена: часть спроса кластера исполнялась из других кластеров во время вероятного дефицита.")
    if "REGIME_GROWTH" in demand_codes and "REGIME_CONFIRMED" in demand_codes:
        messages.append("Рост спроса подтверждается последней полной неделей.")
    if "REGIME_DECLINE" in demand_codes and "REGIME_CONFIRMED" in demand_codes:
        messages.append("Снижение спроса подтверждается последней полной неделей.")
    if need.comparability is HorizonComparability.DIFFERENT_HORIZON:
        messages.append(f"Горизонты различаются: Ozon {need.ozon_horizon_days} дней, наш расчёт {need.horizon_days} дней.")
    blockers = set(need.blocker_codes)
    if "MISSING_DEMAND_ESTIMATE" in blockers:
        messages.append("Потребность не рассчитана: недостаточно истории спроса.")
    if "MISSING_FBO_STOCK" in blockers:
        messages.append("Потребность не рассчитана: нет данных об остатке FBO.")
    if "MISSING_INBOUND" in blockers:
        messages.append("Потребность не рассчитана: нет данных о товарах в пути.")
    if route_incomplete:
        messages.append("Экономический эффект локального размещения не рассчитан: не хватает тарифов, экономики или физической доступности маршрута.")
    if not messages:
        messages.append("План рассчитан по доступным данным спроса, запасов, экономики и ограничений поставки.")
    return tuple(messages)
