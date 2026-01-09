from dolphin.lib.ontology.basic.base import ConceptInstance


class Object(ConceptInstance):
    """A concrete instance (object) representing a Concept.

        The Object must adhere to the member contract defined by its associated Concept.
        The values of members can be any Python type, or references to other Object/Relation.
    """

    pass  # All basic functions inherit from ConceptInstance
