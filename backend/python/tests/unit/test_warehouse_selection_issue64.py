import unittest
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, Point

from graph_service.domain import LogisticsNode, VerificationStatus, GraphRole
from graph_service.algorithms import FacilityService, WarehouseInput, WAREHOUSE_OSM_TAGS


class TestWarehouseSelectionIssue64(unittest.TestCase):
    def setUp(self):
        self.facility_service = FacilityService()

    def test_classify_tags(self):
        """
        Проверяет классификацию тегов по правилам #64:
        eligible, review, excluded.
        """
        # 1. Автоотбор: building=warehouse
        decision, kind, reason, tags = FacilityService._classify({"building": "warehouse"})
        self.assertEqual(decision, "eligible")
        self.assertEqual(kind, "building")
        self.assertEqual(reason, "warehouse_tag")
        self.assertIn("building=warehouse", tags)

        # 2. Автоотбор: building:use=warehouse
        decision, kind, reason, tags = FacilityService._classify({"building:use": "warehouse"})
        self.assertEqual(decision, "eligible")
        self.assertEqual(kind, "building")
        self.assertEqual(reason, "warehouse_tag")

        # 3. Автоотбор: industrial=warehouse (площадка)
        decision, kind, reason, tags = FacilityService._classify({"industrial": "warehouse"})
        self.assertEqual(decision, "eligible")
        self.assertEqual(kind, "site")
        self.assertEqual(reason, "warehouse_tag")

        # 4. Конфликт назначения building:use != warehouse
        decision, kind, reason, tags = FacilityService._classify({
            "building": "warehouse",
            "building:use": "office",
        })
        self.assertEqual(decision, "review")
        self.assertEqual(reason, "conflicting_building_use")

        # 5. Заброшенный / неактивный объект
        decision, kind, reason, tags = FacilityService._classify({
            "building": "warehouse",
            "disused": "yes",
        })
        self.assertEqual(decision, "review")
        self.assertEqual(reason, "inactive_object")

        # 6. Спорные объекты: industrial=logistics и amenity=warehouse
        decision, kind, reason, tags = FacilityService._classify({"industrial": "logistics"})
        self.assertEqual(decision, "review")
        self.assertEqual(reason, "warehouse_use_to_check")

        decision, kind, reason, tags = FacilityService._classify({"amenity": "warehouse"})
        self.assertEqual(decision, "review")
        self.assertEqual(reason, "warehouse_use_to_check")

        # 7. Складское слово в названии без прямых складских тегов
        decision, kind, reason, tags = FacilityService._classify({
            "name": "Центральный логистический склад",
            "building": "yes",
        })
        self.assertEqual(decision, "review")
        self.assertEqual(reason, "warehouse_word_in_name")

        # 8. Исключение промышленных объектов без складских признаков
        decision, kind, reason, tags = FacilityService._classify({
            "landuse": "industrial",
            "building": "industrial",
            "name": "Завод металлоконструкций",
        })
        self.assertEqual(decision, "excluded")
        self.assertEqual(reason, "no_warehouse_evidence")

    def test_invalid_geometry_sent_to_review(self):
        """
        Проверяет, что складские объекты без координат или с некорректными координатами
        отправляются в review.
        """
        objects = [
            WarehouseInput(
                osm_id="osm:way/1",
                tags={"building": "warehouse"},
                latitude=None,
                longitude=30.0,
            ),
            WarehouseInput(
                osm_id="osm:way/2",
                tags={"building": "warehouse"},
                latitude=150.0,  # Недопустимая широта > 90
                longitude=30.0,
            ),
            WarehouseInput(
                osm_id="osm:way/3",
                tags={"building": "warehouse"},
                latitude=59.9,
                longitude=30.3,
                polygon_area_m2=1500.0,
            ),
        ]
        selected, audit = FacilityService.select_warehouses(objects)
        audit_by_id = {row["osm_id"]: row for row in audit}

        self.assertEqual(audit_by_id["osm:way/1"]["decision"], "review")
        self.assertEqual(audit_by_id["osm:way/1"]["reason"], "missing_or_invalid_geometry")
        self.assertEqual(audit_by_id["osm:way/2"]["decision"], "review")
        self.assertEqual(audit_by_id["osm:way/2"]["reason"], "missing_or_invalid_geometry")
        self.assertEqual(audit_by_id["osm:way/3"]["decision"], "selected")
        self.assertEqual(len(selected), 1)

    def test_complex_clustering_and_operator_matching(self):
        """
        Проверяет правило 'Один комплекс — одна вершина':
        - Корпуса внутри площадки объединяются, если совпадает оператор или название.
        - Площадь комплекса суммируется по корпусам.
        - Корпуса с другим оператором остаются отдельными объектами.
        """
        objects = [
            # Площадка складского комплекса
            WarehouseInput(
                osm_id="osm:way/site1",
                tags={"industrial": "warehouse", "name": "Логопарк Юг", "operator": "PNK Group"},
                latitude=59.80,
                longitude=30.40,
                polygon_area_m2=80000.0,
            ),
            # Корпус 1 (тот же оператор)
            WarehouseInput(
                osm_id="osm:way/bld1",
                tags={"building": "warehouse", "name": "Корпус 1", "operator": "PNK Group"},
                latitude=59.801,
                longitude=30.401,
                polygon_area_m2=12000.0,
                enclosing_site_ids=("osm:way/site1",),
            ),
            # Корпус 2 (то же название комплекса)
            WarehouseInput(
                osm_id="osm:way/bld2",
                tags={"building": "warehouse", "name": "Логопарк Юг"},
                latitude=59.802,
                longitude=30.402,
                polygon_area_m2=18000.0,
                enclosing_site_ids=("osm:way/site1",),
            ),
            # Корпус 3 (другой оператор внутри той же площадки -> независимый)
            WarehouseInput(
                osm_id="osm:way/bld3",
                tags={"building": "warehouse", "name": "Склад Арендатора", "operator": "Ozon"},
                latitude=59.803,
                longitude=30.403,
                polygon_area_m2=5000.0,
                enclosing_site_ids=("osm:way/site1",),
            ),
        ]

        selected, audit = FacilityService.select_warehouses(objects)
        audit_by_id = {row["osm_id"]: row for row in audit}

        # Площадка стала выбранной вершиной
        self.assertEqual(audit_by_id["osm:way/site1"]["decision"], "selected")
        # Суммарная площадь комплекса = 12000 + 18000 = 30000 м2
        self.assertEqual(audit_by_id["osm:way/site1"]["warehouse_area_m2"], 30000.0)

        # Корпуса 1 и 2 сгруппированы в площадку
        self.assertEqual(audit_by_id["osm:way/bld1"]["decision"], "grouped")
        self.assertEqual(audit_by_id["osm:way/bld1"]["parent_osm_id"], "osm:way/site1")
        self.assertEqual(audit_by_id["osm:way/bld2"]["decision"], "grouped")
        self.assertEqual(audit_by_id["osm:way/bld2"]["parent_osm_id"], "osm:way/site1")

        # Корпус 3 с другим оператором остался отдельным складом
        self.assertEqual(audit_by_id["osm:way/bld3"]["decision"], "selected")

        # Проверяем итоговый список selected
        selected_ids = {item["id"] for item in selected}
        self.assertIn("warehouse_osm_way_site1", selected_ids)
        self.assertIn("warehouse_osm_way_bld3", selected_ids)
        self.assertEqual(len(selected), 2)

        # Проверяем source_osm_ids площадки
        site_node = next(item for item in selected if item["id"] == "warehouse_osm_way_site1")
        self.assertIn("osm:way/site1", site_node["source_osm_ids"])
        self.assertIn("osm:way/bld1", site_node["source_osm_ids"])
        self.assertIn("osm:way/bld2", site_node["source_osm_ids"])

    def test_ambiguous_site_membership_sent_to_review(self):
        """
        Если корпус попадает в несколько подходящих площадок, спорные площадки
        отправляются в review (ambiguous_complex_membership), а корпус не объединяется.
        """
        objects = [
            WarehouseInput(
                osm_id="osm:way/siteA",
                tags={"industrial": "warehouse", "name": "Площадка А"},
                latitude=59.80,
                longitude=30.40,
                polygon_area_m2=50000.0,
            ),
            WarehouseInput(
                osm_id="osm:way/siteB",
                tags={"industrial": "warehouse", "name": "Площадка Б"},
                latitude=59.80,
                longitude=30.40,
                polygon_area_m2=60000.0,
            ),
            WarehouseInput(
                osm_id="osm:way/bld1",
                tags={"building": "warehouse", "name": "Общий склад"},
                latitude=59.801,
                longitude=30.401,
                polygon_area_m2=10000.0,
                enclosing_site_ids=("osm:way/siteA", "osm:way/siteB"),
            ),
        ]

        selected, audit = FacilityService.select_warehouses(objects)
        audit_by_id = {row["osm_id"]: row for row in audit}

        self.assertEqual(audit_by_id["osm:way/siteA"]["decision"], "review")
        self.assertEqual(audit_by_id["osm:way/siteA"]["reason"], "ambiguous_complex_membership")
        self.assertEqual(audit_by_id["osm:way/siteB"]["decision"], "review")
        self.assertEqual(audit_by_id["osm:way/siteB"]["reason"], "ambiguous_complex_membership")
        self.assertEqual(audit_by_id["osm:way/bld1"]["decision"], "selected")

    def test_limit_and_priority_sorting(self):
        """
        Проверяет ранжирование по лимиту:
        1. Склады с известной площадью по убыванию.
        2. Склады с неизвестной площадью.
        3. Заполненность name и operator.
        4. Детерминированный порядок по osm_id.
        """
        objects = [
            # A: известная площадь 5000
            WarehouseInput(
                osm_id="osm:way/A",
                tags={"building": "warehouse", "name": "Склад A"},
                latitude=59.8,
                longitude=30.1,
                polygon_area_m2=5000.0,
            ),
            # B: известная площадь 20000 (должен быть первым)
            WarehouseInput(
                osm_id="osm:way/B",
                tags={"building": "warehouse", "name": "Склад B"},
                latitude=59.8,
                longitude=30.2,
                polygon_area_m2=20000.0,
            ),
            # C: неизвестная площадь, есть имя и оператор
            WarehouseInput(
                osm_id="osm:node/C",
                tags={"building": "warehouse", "name": "Склад C", "operator": "ТК"},
                latitude=59.8,
                longitude=30.3,
                polygon_area_m2=None,
            ),
            # D: неизвестная площадь, только имя
            WarehouseInput(
                osm_id="osm:node/D",
                tags={"building": "warehouse", "name": "Склад D"},
                latitude=59.8,
                longitude=30.4,
                polygon_area_m2=None,
            ),
        ]

        # Лимит 2: должны пройти B (20000) и A (5000)
        selected, audit = FacilityService.select_warehouses(objects, limit=2)
        audit_by_id = {row["osm_id"]: row for row in audit}

        selected_osm_ids = [item["source_osm_ids"][0] for item in selected]
        self.assertEqual(selected_osm_ids, ["osm:way/B", "osm:way/A"])

        self.assertEqual(audit_by_id["osm:way/B"]["decision"], "selected")
        self.assertEqual(audit_by_id["osm:way/A"]["decision"], "selected")
        self.assertEqual(audit_by_id["osm:node/C"]["decision"], "over_limit")
        self.assertEqual(audit_by_id["osm:node/C"]["reason"], "selection_limit")
        self.assertEqual(audit_by_id["osm:node/D"]["decision"], "over_limit")

        # Лимит 3: должен добавиться C (с именем и оператором), но не D
        selected_3, audit_3 = FacilityService.select_warehouses(objects, limit=3)
        selected_osm_ids_3 = [item["source_osm_ids"][0] for item in selected_3]
        self.assertEqual(selected_osm_ids_3, ["osm:way/B", "osm:way/A", "osm:node/C"])

        # Невалидный лимит
        with self.assertRaises(ValueError):
            FacilityService.select_warehouses(objects, limit=0)
        with self.assertRaises(ValueError):
            FacilityService.select_warehouses(objects, limit=-5)
        with self.assertRaises(ValueError):
            FacilityService.select_warehouses(objects, limit=True)

    def test_select_warehouses_from_gdf_and_node_generation(self):
        """
        Проверяет полный пайплайн от GeoDataFrame до генерации LogisticsNode
        с вычислением площади через EPSG:6933 и пространственным вхождением корпусов.
        """
        # Создаем полигон площадки (в WGS84)
        site_poly = Polygon([(30.0, 59.0), (30.05, 59.0), (30.05, 59.05), (30.0, 59.05)])
        # Полигон здания внутри площадки
        bld_poly = Polygon([(30.01, 59.01), (30.02, 59.01), (30.02, 59.02), (30.01, 59.02)])
        # Точка отдельного склада
        pt_warehouse = Point(30.1, 59.1)

        data = [
            {
                "industrial": "warehouse",
                "name": "Логистический Комплекс Восток",
                "operator": "Восток Логистик",
                "geometry": site_poly,
            },
            {
                "building": "warehouse",
                "name": "Склад Корпус 1",
                "operator": "Восток Логистик",
                "geometry": bld_poly,
            },
            {
                "building": "warehouse",
                "name": "Складской терминал Приморский",
                "geometry": pt_warehouse,
            },
        ]

        gdf = gpd.GeoDataFrame(data, geometry="geometry", crs="EPSG:4326", index=[
            ("way", 1001),
            ("way", 1002),
            ("node", 1003),
        ])

        nodes, audit = self.facility_service.select_warehouse_nodes_from_gdf(gdf, region_id="ru-spb")
        self.assertEqual(len(nodes), 2)
        self.assertEqual(len(self.facility_service.last_audit_log), 3)

        # Проверяем полученные LogisticsNode
        site_node = next(n for n in nodes if "Восток" in n.name)
        standalone_node = next(n for n in nodes if "Приморский" in n.name)

        self.assertIsInstance(site_node, LogisticsNode)
        self.assertIn("osm:way/1001", site_node.source_osm_ids)
        self.assertIn("osm:way/1002", site_node.source_osm_ids)
        self.assertGreater(site_node.identification_basis["warehouse_area_m2"], 0)
        self.assertEqual(site_node.identification_basis["tag_strength"], "strong")

        self.assertIsInstance(standalone_node, LogisticsNode)
        self.assertIn("osm:node/1003", standalone_node.source_osm_ids)
        self.assertIsNone(standalone_node.identification_basis["warehouse_area_m2"])


if __name__ == "__main__":
    unittest.main()

