from app import create_app
from app.extensions import db
from app.dedup import count_no_mbi_clusters
from app.models import Customer, Policy

app = create_app()
with app.app_context():
    print("duplicate badge now:", count_no_mbi_clusters(1), "(was 6)")
    for kid, lid, nm in [(14561, 1610, "Blanche Schwarz"), (6247, 6245, "Jana Benson")]:
        print("=== %s ===" % nm)
        k = db.session.get(Customer, kid)
        l = db.session.get(Customer, lid)
        print("   keeper %s: mbi=%r exists=%s" % (kid, (k.mbi if k else None), k is not None))
        loser_state = "DELETED" if l is None else ("STILL EXISTS mbi=%r" % l.mbi)
        print("   loser %s: %s" % (lid, loser_state))
        for p in Policy.query.filter_by(customer_id=kid).all():
            print("      [%s] %s mid=%r plan=%r type=%s"
                  % (p.status, p.carrier, p.member_id, p.plan_name, p.plan_type))
