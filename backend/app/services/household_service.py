"""Own household facts used by calendar assumptions."""
from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.errors import Conflict, NotFound, Refused


def list_members(db: Session, client_id: int) -> list[models.HouseholdMember]:
    return db.query(models.HouseholdMember).filter_by(client_id=client_id).order_by(models.HouseholdMember.id).all()


def save_member(db: Session, client_id: int, payload: schemas.HouseholdMemberCreate | schemas.HouseholdMemberUpdate, member_id: int | None = None) -> models.HouseholdMember:
    row = None
    if member_id is not None:
        row = db.query(models.HouseholdMember).filter_by(client_id=client_id, id=member_id).first()
        if row is None:
            raise NotFound("世帯の構成員が見つかりません。", en="Household member not found.")
    values = payload.model_dump(exclude_unset=True)
    if "name" in values:
        name = (values["name"] or "").strip()
        if not name:
            raise Refused("名前を入力してください。", en="Enter a name.", status_code=422)
        duplicate = db.query(models.HouseholdMember).filter_by(client_id=client_id, name=name).first()
        if duplicate and (row is None or duplicate.id != row.id):
            raise Conflict("この名前は登録済みです。", en="This name is already registered.")
        values["name"] = name
    if "birth_date" in values and values["birth_date"] is None:
        raise Refused("生年月日を入力してください。", en="Enter a date of birth.", status_code=422)
    if row is None:
        row = models.HouseholdMember(client_id=client_id, **values)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def delete_member(db: Session, client_id: int, member_id: int) -> None:
    row = db.query(models.HouseholdMember).filter_by(client_id=client_id, id=member_id).first()
    if row is None:
        raise NotFound("世帯の構成員が見つかりません。", en="Household member not found.")
    db.delete(row)
    db.commit()
